"""Team roles (data) and the budget policy.

Roles live in config/skills.json, the skills loader's file. Each role entry has its model
alias and skill ids; the role that leads a level of the hierarchy also names the level:

    "director": {"level": "director", "model": "nemotron-3-ultra", "skills": [], ...}

There must be exactly one role each for `director`, `manager` and `auditor`. Every other
role is an operator role, staffed from the operator catalog (`OperatorSpec`). An optional
`max_tokens` sets that role's `max_tokens` per call; without it the model's default
from config/harness.json applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from rookwise.money import require_decimal
from rookwise.skills import load_config

TeamLevel = Literal["director", "manager", "auditor"]
TEAM_LEVELS: tuple[TeamLevel, ...] = ("director", "manager", "auditor")


@dataclass(frozen=True)
class RoleSpec:
    role: str
    level: TeamLevel
    model: str
    skills: tuple[str, ...]
    max_tokens: int | None = None


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
            role, level, spec["model"], tuple(spec.get("skills", [])), spec.get("max_tokens")
        )
    missing = [level for level in TEAM_LEVELS if level not in found]
    if missing:
        raise ValueError(f"no role in the skills config leads the level(s) {missing}")
    return TeamRoles(**found)


@dataclass(frozen=True)
class BudgetPolicy:
    """How the run budget is split. The defaults are placeholders, not measured; they
    are to be tuned after the benchmark.

    - The director's plan call is drawn from the run itself.
    - `auditor_share` of what is free after the plan goes to the auditor's allocation
      first, so the managers cannot spend it.
    - What is then free is split equally among the plan's blocks, one allocation each.
    - A manager keeps `manager_share` of its allocation free for its own call and splits
      the rest equally among its tasks; each operator assignment gets its own allocation.
    - A failed operator is replaced by the next catalog operator for the same role, up
      to `max_reassignments` times, unless it stopped on its budget.
    """

    auditor_share: Decimal = Decimal("0.25")
    manager_share: Decimal = Decimal("0.30")
    max_reassignments: int = 1
    max_blocks: int = 5
    max_tasks_per_block: int = 5
    operator_max_input_tokens: int = 50_000
    operator_max_output_tokens: int = 5_000
    operator_deadline_s: int = 120

    def __post_init__(self) -> None:
        for name in ("auditor_share", "manager_share"):
            share = require_decimal(getattr(self, name), name)
            if share > 1:
                raise ValueError(f"{name} must be between 0 and 1, not {share}")
