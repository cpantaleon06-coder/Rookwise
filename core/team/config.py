"""Team roles (data) and the budget policy.

Roles live in config/skills.json, the skills loader's file. Each role entry has its model
alias and skill ids; the role that leads a level of the hierarchy also names the level:

    "director": {"level": "director", "model": "nemotron-3-ultra", "skills": [], ...}

There must be exactly one role each for `director`, `manager` and `auditor`. Every other
role is an operator role, staffed from the operator catalog (`OperatorSpec`). Every role
sets `max_output_tokens`, the `max_tokens` of each of its calls and so what the ledger
reserves for the output (`rookwise.skills.role_max_output_tokens`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from rookwise.money import require_decimal
from rookwise.skills import load_config, role_max_output_tokens

TeamLevel = Literal["director", "manager", "auditor"]
TEAM_LEVELS: tuple[TeamLevel, ...] = ("director", "manager", "auditor")


@dataclass(frozen=True)
class RoleSpec:
    role: str
    level: TeamLevel
    model: str
    skills: tuple[str, ...]
    max_output_tokens: int
    # Optional request settings (config/skills.json), off when None. Only the director
    # takes `plan_response_format` ("json_schema": its plan call is sent with the plan's
    # schema, inlined, as a wrapped json_schema response_format). `repair_temperature`
    # is the temperature from the first re-prompt on (protocol errors and repairs).
    plan_response_format: Literal["json_schema"] | None = None
    repair_temperature: float | None = None


@dataclass(frozen=True)
class TeamRoles:
    director: RoleSpec
    manager: RoleSpec
    auditor: RoleSpec


def load_team_roles(config: dict[str, Any] | None = None) -> TeamRoles:
    """The director, manager and auditor roles from a skills config (the repo's when None)."""
    config = config if config is not None else load_config()
    found: dict[str, RoleSpec] = {}
    for role, spec in config["roles"].items():
        level = spec.get("level")
        if level is None:
            continue
        if level not in TEAM_LEVELS:
            raise ValueError(f"role {role}: level must be one of {TEAM_LEVELS}, not {level!r}")
        if level in found:
            raise ValueError(f"two roles lead the {level} level: {found[level].role} and {role}")
        plan_format = spec.get("plan_response_format")
        if plan_format not in (None, "json_schema"):
            raise ValueError(f"role {role}: plan_response_format must be null or json_schema")
        if plan_format is not None and level != "director":
            raise ValueError(f"role {role}: only the director has a plan call")
        temperature = spec.get("repair_temperature")
        if temperature is not None and (
            isinstance(temperature, bool)
            or not isinstance(temperature, int | float)
            or not 0 <= temperature <= 2
        ):
            raise ValueError(f"role {role}: repair_temperature must be null or in 0..2")
        found[level] = RoleSpec(
            role,
            level,
            spec["model"],
            tuple(spec.get("skills", [])),
            role_max_output_tokens(role, config),
            plan_format,
            None if temperature is None else float(temperature),
        )
    missing = [level for level in TEAM_LEVELS if level not in found]
    if missing:
        raise ValueError(f"no role in the skills config leads the level(s) {missing}")
    return TeamRoles(**found)


BUDGET_PATH = Path(__file__).resolve().parents[2] / "config" / "budget.json"


@dataclass(frozen=True)
class BudgetPolicy:
    """How the run budget is split (config/budget.json; `load_budget_policy`). The
    values are placeholders, not measured; they are to be tuned after the benchmark.

    - The director's plan call is drawn from the run itself.
    - Of what is free after the plan, `auditor_share` goes to the auditor's allocation
      and `director_share` stays free in the run for the director's diagnosis (and its one
      repair); the managers cannot spend either.
    - The rest goes to the plan's blocks by max-min fairness over their estimated need,
      one block at a time from the smallest need to the largest: each gets the smaller of
      its need and an equal share of what remains, and the last (largest) block gets the
      rest. A block's need is what its pool needs to run its slices one after another:
      their expected costs (the calibrated input estimate plus
      `expected_output_tokens_per_operator`) plus the headroom for the task in flight,
      divided by 1 - `manager_share`. With `pool_covers_one_retry` that headroom is the
      task's first reservation plus the reservation of one retry with its history (the
      first request, a reply of the role's whole output ceiling at
      `retry_reply_chars_per_token` characters per token, and `retry_feedback_chars` of
      feedback), less its expected cost, for the task where it is largest; without it, the
      first reservation alone. So a one-slice block covers its first call and one repair
      or re-prompt when the cap allows it. Blocks run in that order and are
      allocated just before they run, so money an earlier block left unspent goes back to
      the run and reaches the later ones.
    - A manager keeps `manager_share` of its block for its own calls; the rest is the
      block's operator pool, a ledger allocation all its operators reserve from. Money is
      held only while a call is in flight, so operators that run one after another hold
      one reservation at a time.
    - One task may spend at most `task_limit_first_rung_reservations` times its first
      reservation plus `task_limit_next_rung_reservations` times the same request's
      reservation one rung up the model ladder (`escalation.next`), so a reassignment one
      rung up can fit. It is counted as money spent through the ledger's task cap;
      nothing is carved out of the pool for it.
    - With `pool_top_up`, a block pool that cannot cover its next task (that task's
      first reservation plus its retry reservation) draws one extra allocation from the
      run's unallocated money: what is free in the run less `director_share` and less the
      needs of the blocks that have not run yet. It is at most `pool_top_up_max_ratio`
      times the pool's own allocation and is drawn only if it covers that task's first
      reservation. The auditor's allocation is never touched, and the ledger still
      refuses whatever the run cap cannot cover. What the extra allocation leaves unspent
      goes back to the run when the block ends.
    - A failed operator is replaced by the next catalog operator for the same role, up
      to `max_reassignments` times, unless it stopped on its budget.
    """

    auditor_share: Decimal = Decimal("0.25")
    director_share: Decimal = Decimal("0.20")
    manager_share: Decimal = Decimal("0.30")
    task_limit_first_rung_reservations: int = 3
    task_limit_next_rung_reservations: int = 1
    # Expected output of one operator reply, to size the blocks. Measured on the smoke
    # bundle only: the mean operator output of the second smoke record run
    # (runs/cassettes/team_smoke.run2.json), not of inc-01 operators.
    expected_output_tokens_per_operator: int = 1889
    # The pool's headroom covers one retry with history (see above). 4.02 is the 90th
    # percentile of JSON-escaped characters per output token over the 70 inc-01 operator
    # replies longer than 50 tokens (2026-10-21); 1200 is above the longest feedback
    # message seen there (1038 characters). Both are measured on inc-01 only.
    pool_covers_one_retry: bool = True
    retry_reply_chars_per_token: Decimal = Decimal("4.02")
    retry_feedback_chars: int = 1200
    # An exhausted block pool may draw extra money from the run's unallocated balance,
    # at most this ratio of its own allocation. Placeholders (2026-10-24), after the third
    # inc-01 run, where pool b-3 ran dry with USD 0.24 of the cap unspent.
    pool_top_up: bool = True
    pool_top_up_max_ratio: Decimal = Decimal("1.0")
    max_reassignments: int = 1
    max_blocks: int = 5
    max_tasks_per_block: int = 5
    operator_max_input_tokens: int = 50_000
    operator_max_output_tokens: int = 5_000
    # Caps on one operator reply, said in the operator prompt. The findings model rejects
    # a reply over the claim cap (a repair) and keeps the first citations of a claim over
    # the citation cap, by position (no repair). First guesses (2026-10-22), to be tuned
    # on the dev incidents.
    operator_max_claims: int = 4
    operator_max_citations_per_claim: int = 5
    operator_deadline_s: int = 120
    # Above this estimated input a manager consolidates its findings in batches.
    manager_max_input_tokens: int = 60_000

    def __post_init__(self) -> None:
        for name in ("auditor_share", "director_share", "manager_share"):
            share = require_decimal(getattr(self, name), name)
            if not 0 <= share <= 1:
                raise ValueError(f"{name} must be between 0 and 1, not {share}")
        if self.auditor_share + self.director_share >= 1:
            raise ValueError("auditor_share + director_share must leave money for the blocks")
        if self.expected_output_tokens_per_operator < 1:
            raise ValueError("expected_output_tokens_per_operator must be at least 1")
        ratio = require_decimal(self.retry_reply_chars_per_token, "retry_reply_chars_per_token")
        if ratio <= 0:
            raise ValueError("retry_reply_chars_per_token must be positive")
        top_up = require_decimal(self.pool_top_up_max_ratio, "pool_top_up_max_ratio")
        if top_up < 0:
            raise ValueError("pool_top_up_max_ratio must not be negative")
        if self.retry_feedback_chars < 0:
            raise ValueError("retry_feedback_chars must not be negative")
        if self.operator_max_claims < 1 or self.operator_max_citations_per_claim < 1:
            raise ValueError(
                "operator_max_claims and operator_max_citations_per_claim must be at least 1"
            )
        if self.manager_max_input_tokens < 1:
            raise ValueError("manager_max_input_tokens must be at least 1")
        if self.task_limit_first_rung_reservations < 1:
            raise ValueError("task_limit_first_rung_reservations must be at least 1")
        if self.task_limit_next_rung_reservations < 0:
            raise ValueError("task_limit_next_rung_reservations must not be negative")


def load_budget_policy(path: Path = BUDGET_PATH) -> BudgetPolicy:
    """The budget policy in config/budget.json (shares are decimal strings)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    values = {k: v for k, v in data.items() if not k.startswith("_")}
    for name in ("auditor_share", "director_share", "manager_share"):
        values[name] = Decimal(values[name])
    for name in ("retry_reply_chars_per_token", "pool_top_up_max_ratio"):
        if name in values:
            values[name] = Decimal(values[name])
    return BudgetPolicy(**values)
