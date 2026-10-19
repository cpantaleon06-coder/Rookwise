"""The team hierarchy (director, managers, operators, auditor) on top of the harness.

Public surface:

- `run_team(goal, run_id=..., harness=..., store=..., catalog=..., evidence=..., ...)`
  runs one goal through the hierarchy and returns a `TeamRun`: its contract events, the
  plan, one `BlockOutcome` per manager with its `TaskOutcome`s (one per slice), the
  audit verdict, the evidence report, notes on budget stops and escalations, the ledger's
  report, and `unread_slices` (`UnreadRange`s no completed task read) and the empty
  sources. The run must already be open in the harness's ledger.
- `plan_model`, `findings_model`: the run-bound output models of the director and the
  operators (they check the plan reads every source and every quote sits in one line).
- `load_team_roles`, `RoleSpec`, `TeamRoles`: the director, manager and auditor roles,
  which are data in config/skills.json (`level`, `model`, `skills`,
  `max_output_tokens`).
- `BudgetPolicy`: how the run budget is split into ledger allocations.
- `EventLog`: events in the API contract's types, validated when emitted.
- Output models: `Plan`, `PlanBlock`, `PlanTask`, `Findings`, `BlockSummary`,
  `AuditJudgment`, `AuditPoint`.

The flow and the budget rules are described in `rookwise.team.flow`; the auditor's two
steps in `rookwise.team.auditor`.
"""

from rookwise.team.config import BudgetPolicy, RoleSpec, TeamRoles, load_team_roles
from rookwise.team.events import EventLog
from rookwise.team.flow import BlockOutcome, TaskOutcome, TeamRun, UnreadRange, run_team
from rookwise.team.models import (
    AuditJudgment,
    AuditPoint,
    BlockSummary,
    Findings,
    Plan,
    PlanBlock,
    PlanTask,
    findings_model,
    plan_model,
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
    "UnreadRange",
    "findings_model",
    "load_team_roles",
    "plan_model",
    "run_team",
]
