"""Administrator layer skeleton: the budget ledger (docs/ARCHITECTURE.md).

Deterministic code, no model. Before every model call the caller reserves a worst-case
amount; after the call it charges the real cost, which releases the rest of the
reservation. Caps apply per run, per level and per task. When a reservation would pass
a cap, that scope stops: the reservation is refused with `CapReached`, every later
reservation in the scope is refused too, and `report()` returns what was spent so far,
which the caller hands back as the partial result.

Sub-budgets are allocations. `allocate()` holds a USD amount for one agent out of the
run or out of a parent allocation; a call reserved with that `budget_id` is drawn from
the allocation, so it is never counted twice, and `close()` gives the unspent part back
to the parent. The children of a scope can never hold more than the scope itself: an
allocation that does not fit is refused with `CapReached` (and stops nothing, since
nothing was spent), and a reservation that does not fit its allocation stops that
allocation like any other cap. While an allocation is open, its parent counts its full
amount (or what was really spent in it, if a charge ran over); once closed, only what
was spent in it. Level and task caps keep counting every call, inside allocations or not.

Money is `decimal.Decimal`, never float (`rookwise.money`). Every amount is held in
whole micro-USD, rounded once when it enters the ledger, so all sums are exact:
- costs (reservations and charges) round up (ROUND_CEILING), so the ledger never
  records less than the cost formula gives;
- caps and allocations round down (ROUND_FLOOR), so a limit never allows more than was
  asked;
- predictions round to the nearest micro-USD (ROUND_HALF_EVEN); they gate nothing.
A call's prediction is the caller's `usd_predicted`, or, when that is zero and the caller
passes `predicted_usage` (the tokens it expects), the cost formula on that usage at the
ledger's prices. Every entry keeps its prediction next to its real cost, and `report()`
sums both per run and per model.
Rounding therefore never lets spend pass a cap. A float passed for any amount raises
TypeError. Prices are read from config/prices.json as Decimal, from the JSON text.

The store is an open decision (SQLite or Supabase), so `Ledger` is a protocol and
`InMemoryLedger` is its only implementation.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Protocol

from rookwise.money import ZERO_USD, require_decimal, to_micro_usd
from rookwise.schemas import LedgerEntry, Level

PRICES_PATH = Path(__file__).resolve().parent.parent / "config" / "prices.json"


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens. `cached_input` is None when no cached price is published."""

    input: Decimal
    output: Decimal
    cached_input: Decimal | None = None

    def __post_init__(self) -> None:
        require_decimal(self.input, "input price")
        require_decimal(self.output, "output price")
        if self.cached_input is not None:
            require_decimal(self.cached_input, "cached input price")


def load_prices(path: Path = PRICES_PATH) -> dict[str, ModelPrice]:
    """Prices as Decimal, parsed from the JSON text (never through float)."""
    data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)
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
    """`usd` is `usd_exact` rounded up to whole micro-USD: the amount the ledger uses."""

    usd: Decimal
    billed_output_tokens: int
    cached_price_fallback: bool
    usd_exact: Decimal


def call_cost(price: ModelPrice, usage: Usage) -> CallCost:
    """The "Cost of a call" formula from docs/ARCHITECTURE.md.

    Cached tokens use `cached_input`, or the input price when it is None, which the
    result flags as `cached_price_fallback`. Reasoning tokens count as output; when a
    response reports more reasoning than completion tokens, they are clearly not
    included in `completion_tokens` and are added. The arithmetic is exact in Decimal;
    only the result is rounded, up, to micro-USD.
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
    per_million = (
        (usage.input_tokens - usage.cached_tokens) * price.input
        + usage.cached_tokens * cached_price
        + output * price.output
    )
    exact = per_million.scaleb(-6)
    return CallCost(to_micro_usd(exact, ROUND_CEILING), output, fallback, exact)


def _cap(value: object, name: str) -> Decimal:
    return to_micro_usd(require_decimal(value, name), ROUND_FLOOR)


@dataclass(frozen=True)
class Caps:
    """USD caps for one run, rounded down to micro-USD. A level missing from `level_usd`
    has no level cap."""

    run_usd: Decimal
    level_usd: Mapping[str, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_usd", _cap(self.run_usd, "run_usd"))
        levels = {level: _cap(cap, f"level_usd[{level}]") for level, cap in self.level_usd.items()}
        object.__setattr__(self, "level_usd", levels)


@dataclass(frozen=True)
class Reservation:
    id: str
    run_id: str
    level: Level
    task_id: str
    model: str
    usd: Decimal
    usd_predicted: Decimal
    skills: tuple[str, ...] = ()
    budget_id: str | None = None


@dataclass(frozen=True)
class Allocation:
    """A sub-budget of `usd` held out of `parent` (another allocation, or the run when
    None). `id` is the `budget_id` that calls reserve inside it."""

    id: str
    run_id: str
    parent: str | None
    usd: Decimal


@dataclass(frozen=True)
class AllocationReport:
    """An allocation's state. `spent_usd` and `held_usd` include its children."""

    id: str
    parent: str | None
    usd: Decimal
    spent_usd: Decimal
    held_usd: Decimal
    closed: bool
    released_usd: Decimal


class CapReached(Exception):
    """A reservation or an allocation would pass a cap. A refused reservation stops its
    scope from then on; a refused allocation stops nothing. `scope` is "run", "level",
    "task" or "budget" (an allocation, `key` being its id)."""

    def __init__(
        self,
        scope: str,
        key: str,
        cap_usd: Decimal,
        committed_usd: Decimal,
        requested_usd: Decimal,
    ) -> None:
        super().__init__(
            f"{scope} cap reached for {key}: cap USD {cap_usd}, committed "
            f"USD {committed_usd}, requested USD {requested_usd}"
        )
        self.scope = scope
        self.key = key
        self.cap_usd = cap_usd
        self.committed_usd = committed_usd
        self.requested_usd = requested_usd


@dataclass(frozen=True)
class ModelCost:
    """Predicted versus real for the charged calls of one model in a run."""

    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    usd_real: Decimal
    usd_predicted: Decimal


@dataclass(frozen=True)
class RunReport:
    """What a run spent so far. After a stop, this is the partial result's cost record.
    `held_usd` counts call reservations only; allocations are in `allocations`."""

    run_id: str
    entries: tuple[LedgerEntry, ...]
    spent_usd: Decimal
    held_usd: Decimal
    spent_by_level: Mapping[str, Decimal]
    stops: tuple[CapReached, ...]
    caps: Caps
    allocations: tuple[AllocationReport, ...] = ()
    predicted_usd: Decimal = ZERO_USD
    by_model: Mapping[str, ModelCost] = field(default_factory=dict)


class Ledger(Protocol):
    def open_run(self, run_id: str, caps: Caps) -> None: ...

    def set_task_cap(self, run_id: str, task_id: str, usd: Decimal) -> None: ...

    def allocate(
        self, run_id: str, budget_id: str, usd: Decimal, *, parent: str | None = None
    ) -> Allocation: ...

    def close(self, allocation: Allocation) -> Decimal: ...

    def free(self, run_id: str, budget_id: str | None = None) -> Decimal: ...

    def reserve(
        self,
        run_id: str,
        *,
        level: Level,
        task_id: str,
        model: str,
        input_tokens: int,
        max_output_tokens: int,
        usd_predicted: Decimal,
        skills: Iterable[str] = (),
        budget_id: str | None = None,
        predicted_usage: Usage | None = None,
    ) -> Reservation: ...

    def charge(
        self,
        reservation: Reservation,
        usage: Usage,
        ts: datetime | None = None,
        *,
        usage_estimated: bool = False,
    ) -> LedgerEntry: ...

    def release(self, reservation: Reservation) -> None: ...

    def reservation_usd(self, model: str, input_tokens: int, max_output_tokens: int) -> Decimal: ...

    def report(self, run_id: str) -> RunReport: ...


@dataclass
class _Alloc:
    allocation: Allocation
    closed: bool = False
    released: Decimal = ZERO_USD


@dataclass
class _Run:
    caps: Caps
    task_caps: dict[str, Decimal] = field(default_factory=dict)
    entries: list[LedgerEntry] = field(default_factory=list)
    entry_budgets: list[str | None] = field(default_factory=list)  # parallel to entries
    held: dict[str, Reservation] = field(default_factory=dict)
    allocations: dict[str, _Alloc] = field(default_factory=dict)
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

    def set_task_cap(self, run_id: str, task_id: str, usd: Decimal) -> None:
        cap = _cap(usd, f"task cap for {task_id}")
        with self._lock:
            self._run(run_id).task_caps[task_id] = cap

    def allocate(
        self, run_id: str, budget_id: str, usd: Decimal, *, parent: str | None = None
    ) -> Allocation:
        """Hold `usd` (rounded down to micro-USD) out of `parent`, or out of the run."""
        amount = _cap(usd, f"allocation {budget_id}")
        with self._lock:
            run = self._run(run_id)
            if budget_id in run.allocations:
                raise ValueError(f"allocation {budget_id} already exists in run {run_id}")
            if parent is not None:
                self._open(run, parent)
            self._raise_if_stopped(run, run_id, parent)
            scope, key, cap = self._scope_of(run, run_id, parent)
            committed = self._committed_in(run, parent)
            if committed + amount > cap:
                raise CapReached(scope, key, cap, committed, amount)
            allocation = Allocation(budget_id, run_id, parent, amount)
            run.allocations[budget_id] = _Alloc(allocation)
            return allocation

    def close(self, allocation: Allocation) -> Decimal:
        """Close an allocation and give its unspent part back to the parent. Its calls
        must be settled and its children closed first. Returns the amount released."""
        with self._lock:
            run = self._run(allocation.run_id)
            node = self._open(run, allocation.id)
            ids = self._subtree(run, allocation.id)
            if any(r.budget_id in ids for r in run.held.values()):
                raise ValueError(f"allocation {allocation.id} still holds reservations")
            if any(not run.allocations[i].closed for i in ids - {allocation.id}):
                raise ValueError(f"allocation {allocation.id} has open child allocations")
            node.closed = True
            node.released = max(node.allocation.usd - self._spent_in(run, ids), ZERO_USD)
            return node.released

    def free(self, run_id: str, budget_id: str | None = None) -> Decimal:
        """What can still be reserved or allocated in the run, or in one allocation. Zero
        for a stopped or closed scope."""
        with self._lock:
            run = self._run(run_id)
            if budget_id is not None:
                node = run.allocations.get(budget_id)
                if node is None:
                    raise KeyError(f"no allocation {budget_id} in run {run_id}")
                if node.closed:
                    return ZERO_USD
            if any(key in run.stops for key in self._path(run, run_id, budget_id)):
                return ZERO_USD
            _, _, cap = self._scope_of(run, run_id, budget_id)
            return max(cap - self._committed_in(run, budget_id), ZERO_USD)

    def reserve(
        self,
        run_id: str,
        *,
        level: Level,
        task_id: str,
        model: str,
        input_tokens: int,
        max_output_tokens: int,
        usd_predicted: Decimal,
        skills: Iterable[str] = (),
        budget_id: str | None = None,
        predicted_usage: Usage | None = None,
    ) -> Reservation:
        """Hold the worst case: every input token at full price plus `max_output_tokens`.
        With `budget_id`, the hold is drawn from that open allocation. The prediction is
        `usd_predicted`, or the cost of `predicted_usage` when `usd_predicted` is zero."""
        predicted = to_micro_usd(require_decimal(usd_predicted, "usd_predicted"), ROUND_HALF_EVEN)
        with self._lock:
            run = self._run(run_id)
            if budget_id is not None:
                self._open(run, budget_id)
            price = self._price(model)
            usd = call_cost(price, Usage(input_tokens, max_output_tokens)).usd
            if predicted == 0 and predicted_usage is not None:
                exact = call_cost(price, predicted_usage).usd_exact
                predicted = to_micro_usd(exact, ROUND_HALF_EVEN)
            self._raise_if_stopped(run, run_id, budget_id)
            scope, key, cap = self._scope_of(run, run_id, budget_id)
            checks = [
                (scope, key, cap, self._committed_in(run, budget_id)),
                ("level", level, run.caps.level_usd.get(level), self._flat(run, "level", level)),
                ("task", task_id, run.task_caps.get(task_id), self._flat(run, "task", task_id)),
            ]
            for scope, key, cap, committed in checks:
                stopped = run.stops.get((scope, key))
                if stopped is not None:
                    raise stopped
                if cap is not None and committed + usd > cap:
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
                predicted,
                tuple(skills),
                budget_id,
            )
            run.next_id += 1
            run.held[reservation.id] = reservation
            return reservation

    def charge(
        self,
        reservation: Reservation,
        usage: Usage,
        ts: datetime | None = None,
        *,
        usage_estimated: bool = False,
    ) -> LedgerEntry:
        """Charge the real cost of a finished call and release the rest of its hold.

        `usage_estimated` marks a charge made without reported usage (see LedgerEntry).
        """
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
                usage_estimated=usage_estimated,
            )
            run.entries.append(entry)
            run.entry_budgets.append(reservation.budget_id)
            # Money already spent counts even when it passes a cap; the scope stops.
            scopes = [
                (*self._scope_of(run, reservation.run_id, node), self._committed_in(run, node))
                for node in self._chain(run, reservation.budget_id)
            ]
            for name, value in (("level", reservation.level), ("task", reservation.task_id)):
                caps = run.caps.level_usd if name == "level" else run.task_caps
                scopes.append((name, value, caps.get(value), self._flat(run, name, value)))
            for scope, key, cap, spent in scopes:
                if cap is not None and spent > cap and (scope, key) not in run.stops:
                    run.stops[(scope, key)] = CapReached(scope, key, cap, spent, ZERO_USD)
            return entry

    def reservation_usd(self, model: str, input_tokens: int, max_output_tokens: int) -> Decimal:
        """What `reserve` would hold for such a call, at this ledger's prices. A query:
        nothing is held."""
        return call_cost(self._price(model), Usage(input_tokens, max_output_tokens)).usd

    def release(self, reservation: Reservation) -> None:
        """Drop a hold without a charge, for a call that was never made."""
        with self._lock:
            if self._run(reservation.run_id).held.pop(reservation.id, None) is None:
                raise ValueError(f"reservation {reservation.id} is not held")

    def report(self, run_id: str) -> RunReport:
        with self._lock:
            run = self._run(run_id)
            by_level: dict[str, Decimal] = {}
            by_model: dict[str, ModelCost] = {}
            for entry in run.entries:
                by_level[entry.level] = by_level.get(entry.level, ZERO_USD) + entry.usd_real
                row = by_model.get(entry.model)
                if row is None:
                    row = ModelCost(entry.model, 0, 0, 0, ZERO_USD, ZERO_USD)
                by_model[entry.model] = ModelCost(
                    entry.model,
                    row.calls + 1,
                    row.input_tokens + entry.input_tokens,
                    row.output_tokens + entry.output_tokens,
                    row.usd_real + entry.usd_real,
                    row.usd_predicted + entry.usd_predicted,
                )
            allocations = []
            for node in run.allocations.values():
                ids = self._subtree(run, node.allocation.id)
                allocations.append(
                    AllocationReport(
                        id=node.allocation.id,
                        parent=node.allocation.parent,
                        usd=node.allocation.usd,
                        spent_usd=self._spent_in(run, ids),
                        held_usd=sum(
                            (r.usd for r in run.held.values() if r.budget_id in ids), ZERO_USD
                        ),
                        closed=node.closed,
                        released_usd=node.released,
                    )
                )
            return RunReport(
                run_id=run_id,
                entries=tuple(run.entries),
                spent_usd=sum((e.usd_real for e in run.entries), ZERO_USD),
                held_usd=sum((r.usd for r in run.held.values()), ZERO_USD),
                spent_by_level=by_level,
                stops=tuple(run.stops.values()),
                caps=run.caps,
                allocations=tuple(allocations),
                predicted_usd=sum((e.usd_predicted for e in run.entries), ZERO_USD),
                by_model=by_model,
            )

    # -- helpers (called with the lock held) ---------------------------------------------

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
    def _open(run: _Run, budget_id: str) -> _Alloc:
        node = run.allocations.get(budget_id)
        if node is None:
            raise KeyError(f"no allocation {budget_id}")
        if node.closed:
            raise ValueError(f"allocation {budget_id} is closed")
        return node

    @staticmethod
    def _chain(run: _Run, budget_id: str | None) -> list[str | None]:
        """The allocation, its ancestors, then None for the run itself."""
        chain: list[str | None] = []
        while budget_id is not None:
            chain.append(budget_id)
            budget_id = run.allocations[budget_id].allocation.parent
        return [*chain, None]

    def _path(self, run: _Run, run_id: str, budget_id: str | None) -> list[tuple[str, str]]:
        return [self._scope_of(run, run_id, node)[:2] for node in self._chain(run, budget_id)]

    def _raise_if_stopped(self, run: _Run, run_id: str, budget_id: str | None) -> None:
        for key in self._path(run, run_id, budget_id):
            stopped = run.stops.get(key)
            if stopped is not None:
                raise stopped

    @staticmethod
    def _scope_of(run: _Run, run_id: str, budget_id: str | None) -> tuple[str, str, Decimal]:
        if budget_id is None:
            return "run", run_id, run.caps.run_usd
        return "budget", budget_id, run.allocations[budget_id].allocation.usd

    @staticmethod
    def _subtree(run: _Run, budget_id: str) -> set[str | None]:
        ids: set[str | None] = {budget_id}
        stack = [budget_id]
        while stack:
            parent = stack.pop()
            for child_id, node in run.allocations.items():
                if node.allocation.parent == parent:
                    ids.add(child_id)
                    stack.append(child_id)
        return ids

    @staticmethod
    def _spent_in(run: _Run, ids: set[str | None]) -> Decimal:
        return sum(
            (e.usd_real for e, b in zip(run.entries, run.entry_budgets, strict=True) if b in ids),
            ZERO_USD,
        )

    def _committed_in(self, run: _Run, budget_id: str | None) -> Decimal:
        """Spent plus held directly in this scope, plus each child allocation: its amount
        while open (or more, if it ran over), what was spent in it once closed."""
        committed = self._spent_in(run, {budget_id}) + sum(
            (r.usd for r in run.held.values() if r.budget_id == budget_id), ZERO_USD
        )
        for child_id, node in run.allocations.items():
            if node.allocation.parent != budget_id:
                continue
            if node.closed:
                committed += self._spent_in(run, self._subtree(run, child_id))
            else:
                committed += max(node.allocation.usd, self._committed_in(run, child_id))
        return committed

    @staticmethod
    def _flat(run: _Run, scope: str, key: str) -> Decimal:
        """Everything spent and held for one level or one task, wherever it was reserved."""

        def matches(level: str, task_id: str) -> bool:
            return (level if scope == "level" else task_id) == key

        spent = sum((e.usd_real for e in run.entries if matches(e.level, e.task_id)), ZERO_USD)
        held = sum((r.usd for r in run.held.values() if matches(r.level, r.task_id)), ZERO_USD)
        return spent + held
