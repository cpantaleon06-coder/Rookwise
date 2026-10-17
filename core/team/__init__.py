"""The team hierarchy (director, managers, operators, auditor) on top of the harness.

Public surface:

- `run_team(goal, run_id=..., harness=..., store=..., catalog=..., evidence=..., ...)`
  runs one goal through the hierarchy and returns a `TeamRun`: its contract events, the
  plan, one `BlockOutcome` per manager with its `TaskOutcome`s, the audit verdict, the
  evidence report, notes on budget stops and escalations, and the ledger's report.
  The run must already be open in the harness's ledger.
- `load_team_roles`, `RoleSpec`, `TeamRoles`: the director, manager and auditor roles,
  which are data in config/skills.json (`level`, `model`, `skills`, optional
  `max_tokens`).
- `BudgetPolicy`: how the run budget is split into ledger allocations.
- `EventLog`: events in the API contract's types, validated when emitted.
- Output models: `Plan`, `PlanBlock`, `PlanTask`, `Findings`, `BlockSummary`,
  `AuditJudgment`, `AuditPoint`.

The flow and the budget rules are described in `rookwise.team.flow`; the auditor's two
steps in `rookwise.team.auditor`.
"""

from rookwise.team.config import BudgetPolicy, RoleSpec, TeamRoles, load_team_roles
from rookwise.team.events import EventLog
from rookwise.team.flow import BlockOutcome, TaskOutcome, TeamRun, run_team
from rookwise.team.models import (
    AuditJudgment,
    AuditPoint,
    BlockSummary,
    Findings,
    Plan,
    PlanBlock,
    PlanTask,
)

__all__ = [
    "AuditJudgment",
    "AuditPoint",
    "BlockOutcome",
    "BlockSummary",
    "BudgetPolicy",
    "EventLog",
    "Findings",
    "Plan",
    "PlanBlock",
    "PlanTask",
    "RoleSpec",
    "TaskOutcome",
    "TeamRoles",
    "TeamRun",
    "load_team_roles",
    "run_team",
]
