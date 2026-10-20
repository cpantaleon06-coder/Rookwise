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
        found[level] = RoleSpec(
            role,
            level,
            spec["model"],
            tuple(spec.get("skills", [])),
            role_max_output_tokens(role, config),
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
    - The rest is split among the plan's blocks in proportion to the estimated cost of
      each block's work: every slice's first operator reservation (its prompt through the
      calibrated input estimate plus the role's output ceiling).
    - A manager keeps `manager_share` of its block for its own calls; the rest is the
      block's operator pool, a ledger allocation all its operators reserve from. Money is
      held only while a call is in flight, so operators that run one after another hold
      one reservation at a time.
    - One task may spend at most `operator_task_limit_reservations` times its first
      reservation (an initial attempt, two repairs, one reassignment), counted as money
      spent through the ledger's task cap; nothing is carved out of the pool for it.
    - A failed operator is replaced by the next catalog operator for the same role, up
      to `max_reassignments` times, unless it stopped on its budget.
    """

    auditor_share: Decimal = Decimal("0.25")
    director_share: Decimal = Decimal("0.20")
    manager_share: Decimal = Decimal("0.30")
    operator_task_limit_reservations: int = 4
    max_reassignments: int = 1
    max_blocks: int = 5
    max_tasks_per_block: int = 5
    operator_max_input_tokens: int = 50_000
    operator_max_output_tokens: int = 5_000
    operator_deadline_s: int = 120

    def __post_init__(self) -> None:
        for name in ("auditor_share", "director_share", "manager_share"):
            share = require_decimal(getattr(self, name), name)
            if not 0 <= share <= 1:
                raise ValueError(f"{name} must be between 0 and 1, not {share}")
        if self.auditor_share + self.director_share >= 1:
            raise ValueError("auditor_share + director_share must leave money for the blocks")
        if self.operator_task_limit_reservations < 1:
            raise ValueError("operator_task_limit_reservations must be at least 1")


def load_budget_policy(path: Path = BUDGET_PATH) -> BudgetPolicy:
    """The budget policy in config/budget.json (shares are decimal strings)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    values = {k: v for k, v in data.items() if not k.startswith("_")}
    for name in ("auditor_share", "director_share", "manager_share"):
        values[name] = Decimal(values[name])
    return BudgetPolicy(**values)
