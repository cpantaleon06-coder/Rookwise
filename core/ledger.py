"""Administrator layer skeleton: the budget ledger (docs/ARCHITECTURE.md).

Deterministic code, no model. Before every model call the caller reserves a worst-case
amount; after the call it charges the real cost, which releases the rest of the
reservation. Caps apply per run, per level and per task. When a reservation would pass
a cap, that scope stops: the reservation is refused with `CapReached`, every later
reservation in the scope is refused too, and `report()` returns what was spent so far,
which the caller hands back as the partial result.

The store is an open decision (SQLite or Supabase), so `Ledger` is a protocol and
`InMemoryLedger` is its only implementation.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from rookwise.schemas import LedgerEntry, Level

PRICES_PATH = Path(__file__).resolve().parent.parent / "config" / "prices.json"

# Tolerance for float comparisons against caps, far below any real price step.
_EPS = 1e-12


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens. `cached_input` is None when no cached price is published."""

    input: float
    output: float
    cached_input: float | None = None


def load_prices(path: Path = PRICES_PATH) -> dict[str, ModelPrice]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        model: ModelPrice(p["input"], p["output"], p.get("cached_input"))
        for model, p in data["per_million_tokens"].items()
    }


@dataclass(frozen=True)
class Usage:
    """Usage reported by the API for one call (`prompt_tokens`, `completion_tokens`, ...)."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True)
class CallCost:
    usd: float
    billed_output_tokens: int
    cached_price_fallback: bool


def call_cost(price: ModelPrice, usage: Usage) -> CallCost:
    """The "Cost of a call" formula from docs/ARCHITECTURE.md.

    Cached tokens use `cached_input`, or the input price when it is None, which the
    result flags as `cached_price_fallback`. Reasoning tokens count as output; when a
    response reports more reasoning than completion tokens, they are clearly not
    included in `completion_tokens` and are added.
    """
    if not 0 <= usage.cached_tokens <= usage.input_tokens:
        raise ValueError("cached_tokens must be between 0 and input_tokens")
    if min(usage.output_tokens, usage.reasoning_tokens) < 0:
        raise ValueError("token counts must not be negative")
    output = usage.output_tokens
    if usage.reasoning_tokens > output:
        output += usage.reasoning_tokens
    fallback = price.cached_input is None
    cached_price = price.input if fallback else price.cached_input
    usd = (
        (usage.input_tokens - usage.cached_tokens) * price.input
        + usage.cached_tokens * cached_price
        + output * price.output
    ) / 1_000_000
    return CallCost(round(usd, 12), output, fallback)


@dataclass(frozen=True)
class Caps:
    """USD caps for one run. A level missing from `level_usd` has no level cap."""

    run_usd: float
    level_usd: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Reservation:
    id: str
    run_id: str
    level: Level
    task_id: str
    model: str
    usd: float
    usd_predicted: float
    skills: tuple[str, ...] = ()


class CapReached(Exception):
    """A reservation would pass a cap. The scope is stopped from now on."""

    def __init__(
        self, scope: str, key: str, cap_usd: float, committed_usd: float, requested_usd: float
    ) -> None:
        super().__init__(
            f"{scope} cap reached for {key}: cap USD {cap_usd}, committed "
            f"USD {committed_usd:.6f}, requested USD {requested_usd:.6f}"
        )
        self.scope = scope
        self.key = key
        self.cap_usd = cap_usd
        self.committed_usd = committed_usd
        self.requested_usd = requested_usd


@dataclass(frozen=True)
class RunReport:
    """What a run spent so far. After a stop, this is the partial result's cost record."""

    run_id: str
    entries: tuple[LedgerEntry, ...]
    spent_usd: float
    held_usd: float
    spent_by_level: Mapping[str, float]
    stops: tuple[CapReached, ...]


class Ledger(Protocol):
    def open_run(self, run_id: str, caps: Caps) -> None: ...

    def set_task_cap(self, run_id: str, task_id: str, usd: float) -> None: ...

    def reserve(
        self,
        run_id: str,
        *,
        level: Level,
        task_id: str,
        model: str,
        input_tokens: int,
        max_output_tokens: int,
        usd_predicted: float,
        skills: Iterable[str] = (),
    ) -> Reservation: ...

    def charge(
        self, reservation: Reservation, usage: Usage, ts: datetime | None = None
    ) -> LedgerEntry: ...

    def release(self, reservation: Reservation) -> None: ...

    def report(self, run_id: str) -> RunReport: ...


@dataclass
class _Run:
    caps: Caps
    task_caps: dict[str, float] = field(default_factory=dict)
    entries: list[LedgerEntry] = field(default_factory=list)
    held: dict[str, Reservation] = field(default_factory=dict)
    stops: dict[tuple[str, str], CapReached] = field(default_factory=dict)
    next_id: int = 1


class InMemoryLedger:
    """The `Ledger` protocol in process memory. Safe to share between threads."""

    def __init__(self, prices: Mapping[str, ModelPrice] | None = None) -> None:
        self._prices = dict(prices) if prices is not None else load_prices()
        self._runs: dict[str, _Run] = {}
        self._lock = threading.Lock()

    def open_run(self, run_id: str, caps: Caps) -> None:
        with self._lock:
            if run_id in self._runs:
                raise ValueError(f"run {run_id} is already open")
            self._runs[run_id] = _Run(caps)

    def set_task_cap(self, run_id: str, task_id: str, usd: float) -> None:
        with self._lock:
            self._run(run_id).task_caps[task_id] = usd

    def reserve(
        self,
        run_id: str,
        *,
        level: Level,
        task_id: str,
        model: str,
        input_tokens: int,
        max_output_tokens: int,
        usd_predicted: float,
        skills: Iterable[str] = (),
    ) -> Reservation:
        """Hold the worst case: every input token at full price plus `max_output_tokens`."""
        with self._lock:
            run = self._run(run_id)
            usd = call_cost(self._price(model), Usage(input_tokens, max_output_tokens)).usd
            for scope, key, cap in self._scopes(run, run_id, level, task_id):
                stopped = run.stops.get((scope, key))
                if stopped is not None:
                    raise stopped
                committed = self._committed(run, scope, key)
                if cap is not None and committed + usd > cap + _EPS:
                    stop = CapReached(scope, key, cap, committed, usd)
                    run.stops[(scope, key)] = stop
                    raise stop
            reservation = Reservation(
                f"{run_id}:{run.next_id}",
                run_id,
                level,
                task_id,
                model,
                usd,
                usd_predicted,
                tuple(skills),
            )
            run.next_id += 1
            run.held[reservation.id] = reservation
            return reservation

    def charge(
        self, reservation: Reservation, usage: Usage, ts: datetime | None = None
    ) -> LedgerEntry:
        """Charge the real cost of a finished call and release the rest of its hold."""
        with self._lock:
            run = self._run(reservation.run_id)
            if run.held.pop(reservation.id, None) is None:
                raise ValueError(f"reservation {reservation.id} is not held")
            cost = call_cost(self._price(reservation.model), usage)
            entry = LedgerEntry(
                run_id=reservation.run_id,
                level=reservation.level,
                task_id=reservation.task_id,
                model=reservation.model,
                input_tokens=usage.input_tokens,
                cached_tokens=usage.cached_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                cached_price_fallback=cost.cached_price_fallback,
                usd_real=cost.usd,
                usd_predicted=reservation.usd_predicted,
                ts=ts or datetime.now(UTC),
                skills=list(reservation.skills),
            )
            run.entries.append(entry)
            # Money already spent counts even when it passes a cap; the scope stops.
            scopes = self._scopes(run, reservation.run_id, reservation.level, reservation.task_id)
            for scope, key, cap in scopes:
                spent = self._committed(run, scope, key)
                if cap is not None and spent > cap + _EPS and (scope, key) not in run.stops:
                    run.stops[(scope, key)] = CapReached(scope, key, cap, spent, 0.0)
            return entry

    def release(self, reservation: Reservation) -> None:
        """Drop a hold without a charge, for a call that was never made."""
        with self._lock:
            if self._run(reservation.run_id).held.pop(reservation.id, None) is None:
                raise ValueError(f"reservation {reservation.id} is not held")

    def report(self, run_id: str) -> RunReport:
        with self._lock:
            run = self._run(run_id)
            by_level: dict[str, float] = {}
            for entry in run.entries:
                by_level[entry.level] = by_level.get(entry.level, 0.0) + entry.usd_real
            return RunReport(
                run_id=run_id,
                entries=tuple(run.entries),
                spent_usd=sum(e.usd_real for e in run.entries),
                held_usd=sum(r.usd for r in run.held.values()),
                spent_by_level=by_level,
                stops=tuple(run.stops.values()),
            )

    def _run(self, run_id: str) -> _Run:
        try:
            return self._runs[run_id]
        except KeyError:
            raise KeyError(f"run {run_id} is not open") from None

    def _price(self, model: str) -> ModelPrice:
        try:
            return self._prices[model]
        except KeyError:
            raise KeyError(f"no price for model {model} in config/prices.json") from None

    @staticmethod
    def _scopes(
        run: _Run, run_id: str, level: str, task_id: str
    ) -> list[tuple[str, str, float | None]]:
        return [
            ("run", run_id, run.caps.run_usd),
            ("level", level, run.caps.level_usd.get(level)),
            ("task", task_id, run.task_caps.get(task_id)),
        ]

    @staticmethod
    def _committed(run: _Run, scope: str, key: str) -> float:
        def matches(level: str, task_id: str) -> bool:
            return scope == "run" or (level if scope == "level" else task_id) == key

        spent = sum(e.usd_real for e in run.entries if matches(e.level, e.task_id))
        held = sum(r.usd for r in run.held.values() if matches(r.level, r.task_id))
        return spent + held
