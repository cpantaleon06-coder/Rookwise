"""API contract v1 between core/ and web/ (docs/api.md), as pydantic models.

Only the contract lives here: no server, no routes. The JSON Schemas in
docs/api/schemas/ are generated from these models (scripts/gen_api_schemas.py), and the
fixtures in examples/api/ are validated against them (tests/test_api_contract.py).

Field names come from core/ wherever a model exists there: `TaskV1`, `ResultV1` and
`LedgerEntry` (rookwise.schemas), `AttemptRecord` and its outcome labels
(rookwise.harness.escalate), the ledger's `RunReport`, `Caps` and `CapReached` fields
(rookwise.ledger), and the catalog fields of `OperatorSpec` (rookwise.runner). Every
other field is new in this contract; docs/api.md lists them.

The contract is domain-neutral: roles, skills, tools and models are plain strings.

Decided on 2026-10-16 (docs/DECISIONS.md): every run-scoped payload and every event
carries `mode`, so a recorded run is labelled as recorded everywhere; ids such as
`run_id` are opaque strings with a prefix (`run_...`) that the UI must not parse; USD
values are sent exactly as the ledger computes them and the UI formats.

Decided on 2026-10-17 (part of v1): every money field is `rookwise.money.Usd` (or
`PositiveUsd`), a decimal string with exactly six decimals such as "0.002350", never a
JSON number. The ledger computes in Decimal and holds whole micro-USD, so the strings
are exact. `CostReport.prediction_error` is a ratio, not money, and stays a number.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    TypeAdapter,
    model_validator,
)

from rookwise.harness.escalate import AttemptRecord, OutcomeLabel
from rookwise.money import PositiveUsd, Usd
from rookwise.schemas import LedgerEntry, Level, ResultV1, TaskV1

API_VERSION = "v1"

Mode = Literal["recorded", "live"]
RunStatus = Literal[
    "queued",
    "planning",
    "awaiting_approval",
    "running",
    "paused",
    "finished",
    "failed",
    "cancelled",
]
RefusalReason = Literal[
    "live_disabled", "run_cap_exceeded", "daily_cap_reached", "visitor_limit_reached"
]
Sender = Literal["user", "director", "vp"]
AgentStatus = Literal["hired", "working", "idle", "done", "failed"]
TaskStatus = Literal["assigned", "running", "ok", "failed"]
CapScope = Literal["run", "level", "task"]


class _Api(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- errors -------------------------------------------------------------------------------


class ErrorBody(_Api):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(_Api):
    """Every non-2xx response body."""

    error: ErrorBody


# -- modes and caps -----------------------------------------------------------------------


class LiveCaps(_Api):
    """Live demo caps from .env.example: LIVE_DEMO_MAX_USD_PER_RUN,
    LIVE_DEMO_MAX_USD_PER_DAY and LIVE_DEMO_MAX_RUNS_PER_VISITOR_PER_DAY. The visitor is
    known by a signed, anonymous, HttpOnly cookie; `visitor_runs_today` is 0 without one.
    A visitor can clear cookies, so the USD caps are the backstop that cannot be bypassed."""

    max_usd_per_run: Usd
    max_usd_per_day: Usd
    spent_usd_today: Usd
    max_runs_per_visitor_per_day: NonNegativeInt
    visitor_runs_today: NonNegativeInt


class ModeAvailability(_Api):
    mode: Mode
    available: bool
    refusal: RefusalReason | None = None
    detail: str = ""


class RecordingSummary(_Api):
    recording_id: str
    title: str
    goal: str
    simulated_case: bool
    spent_usd: Usd


class ModesView(_Api):
    """GET /api/v1/modes."""

    api_version: Literal["v1"] = "v1"
    default_mode: Mode
    modes: list[ModeAvailability]
    live_caps: LiveCaps
    recordings: list[RecordingSummary]


# -- runs ---------------------------------------------------------------------------------


class RunCaps(_Api):
    """The ledger's `Caps` for the run: `run_usd` and optional per-level caps."""

    run_usd: PositiveUsd
    level_usd: dict[str, Usd] = Field(default_factory=dict)


class CreateRunRequest(_Api):
    """POST /api/v1/runs. Live runs need a goal; recorded runs need a recording_id."""

    mode: Mode
    goal: str | None = Field(default=None, min_length=1, max_length=2000)
    budget_usd: PositiveUsd | None = None
    recording_id: str | None = None
    board: bool = False

    @model_validator(mode="after")
    def _mode_fields(self) -> CreateRunRequest:
        if self.mode == "live" and (self.goal is None or self.budget_usd is None):
            raise ValueError("a live run needs goal and budget_usd")
        if self.mode == "recorded" and self.recording_id is None:
            raise ValueError("a recorded run needs recording_id")
        return self


class RunView(_Api):
    """GET /api/v1/runs/{run_id}. `run_id` is opaque (`run_...`). `spent_usd` and
    `held_usd` are the ledger's RunReport figures; `predicted_usd` is the sum of
    `usd_predicted` over its entries. A recorded run keeps the run_id of the run it was
    recorded from."""

    run_id: str
    goal: str
    mode: Mode
    recording_id: str | None = None
    simulated_case: bool
    status: RunStatus
    board: bool = False
    caps: RunCaps
    spent_usd: Usd
    held_usd: Usd
    predicted_usd: Usd
    created_at: datetime
    finished_at: datetime | None = None
    events_url: str


class RunList(_Api):
    items: list[RunView]
    next_cursor: str | None = None


class ApprovalRequest(_Api):
    """POST /api/v1/runs/{run_id}/approval: the user approves or adjusts the plan."""

    approved: bool
    note: str = Field(default="", max_length=2000)


# -- org chart ----------------------------------------------------------------------------


class AgentNode(_Api):
    """One hired agent. `operator_id`, `role`, `model` and `skills` are catalog fields
    (OperatorSpec); levels are `rookwise.schemas.Level`."""

    agent_id: str
    level: Level
    role: str
    model: str
    operator_id: str | None = None
    parent_id: str | None = None
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    status: AgentStatus


class OrgChart(_Api):
    """GET /api/v1/runs/{run_id}/org: a snapshot as of one event."""

    run_id: str
    mode: Mode
    as_of_event_id: str | None
    nodes: list[AgentNode]


# -- ledger -------------------------------------------------------------------------------


class CapStop(_Api):
    """A stopped scope, with the fields of `rookwise.ledger.CapReached`."""

    scope: CapScope
    key: str
    cap_usd: Usd
    committed_usd: Usd
    requested_usd: Usd


class LedgerView(_Api):
    """GET /api/v1/runs/{run_id}/ledger: `RunReport` plus predictions."""

    run_id: str
    mode: Mode
    caps: RunCaps
    spent_usd: Usd
    held_usd: Usd
    predicted_usd: Usd
    spent_by_level: dict[str, Usd]
    usage_estimated_entries: NonNegativeInt
    entries: list[LedgerEntry]
    stops: list[CapStop] = Field(default_factory=list)


# -- chat ---------------------------------------------------------------------------------


class ChatMessage(_Api):
    """Only the director (or the VP with a board) talks to the user."""

    message_id: str
    run_id: str
    sender: Sender
    text: str
    ts: datetime


class ChatMessageList(_Api):
    run_id: str
    mode: Mode
    items: list[ChatMessage]


class PostMessageRequest(_Api):
    text: str = Field(min_length=1, max_length=4000)


# -- tasks --------------------------------------------------------------------------------


class TaskView(_Api):
    """One operator task with its contracts and attempt records."""

    task: TaskV1
    agent_id: str
    operator_id: str
    status: TaskStatus
    label: OutcomeLabel | None = None
    result: ResultV1 | None = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    tool_calls: dict[str, NonNegativeInt] = Field(default_factory=dict)


class TaskList(_Api):
    run_id: str
    mode: Mode
    items: list[TaskView]


# -- delivery package ---------------------------------------------------------------------


class Deliverable(_Api):
    task_id: str
    output_ref: str
    title: str
    content: Any


class CostReport(_Api):
    """Predicted versus real. `prediction_error` is (real - predicted) / predicted, the
    benchmark metric in docs/ARCHITECTURE.md; None when nothing was predicted."""

    predicted_usd: Usd
    real_usd: Usd
    prediction_error: float | None
    spent_by_level: dict[str, Usd]
    usage_estimated_entries: NonNegativeInt


class ContractRecord(_Api):
    task: TaskV1
    result: ResultV1 | None


class AuditCheck(_Api):
    criterion: str
    passed: bool
    note: str = ""


class AuditVerdict(_Api):
    verdict: Literal["accepted", "rejected", "accepted_with_warning"]
    model: str
    checks: list[AuditCheck]
    correction_cycles: NonNegativeInt
    warning: str | None = None


class DeliveryPackage(_Api):
    """GET /api/v1/runs/{run_id}/package."""

    run_id: str
    mode: Mode
    simulated_case: bool
    summary: str
    deliverables: list[Deliverable]
    cost_report: CostReport
    contracts: list[ContractRecord]
    decisions: list[str]
    audit: AuditVerdict


# -- SSE events ---------------------------------------------------------------------------


class _EventBase(_Api):
    """Common envelope. `id` is "<run_id>:<seq>" and is also the SSE `id:` line; the UI
    treats it as opaque. `mode` labels every event of a recorded run as recorded."""

    id: str
    seq: int = Field(ge=1)
    run_id: str
    mode: Mode
    ts: datetime


class RunStartedPayload(_Api):
    goal: str
    mode: Mode
    recording_id: str | None = None
    budget_usd: PositiveUsd
    board: bool
    simulated_case: bool


class AgentHiredPayload(_Api):
    agent: AgentNode


class TaskAssignedPayload(_Api):
    task: TaskV1
    agent_id: str
    operator_id: str


class TaskStartedPayload(_Api):
    task_id: str
    agent_id: str
    model: str
    attempt_index: NonNegativeInt


class AttemptRecordedPayload(_Api):
    agent_id: str
    attempt: AttemptRecord


class ToolCalledPayload(_Api):
    """One tool execution. `args` is only sent with the debug flag (docs/api.md)."""

    task_id: str
    agent_id: str
    tool: str
    ok: bool
    error_type: str | None = None
    truncated: bool = False
    run_tool_count: NonNegativeInt
    args: dict[str, Any] | None = None


class BudgetUpdatePayload(_Api):
    spent_usd: Usd
    held_usd: Usd
    predicted_usd: Usd
    cap_usd: PositiveUsd
    spent_by_level: dict[str, Usd]
    entry: LedgerEntry | None = None


class MessagePayload(_Api):
    message: ChatMessage


class TaskResultPayload(_Api):
    agent_id: str
    result: ResultV1
    label: OutcomeLabel


class AuditResultPayload(_Api):
    audit: AuditVerdict


class RunFinishedPayload(_Api):
    status: Literal["finished", "cancelled"]
    partial: bool
    spent_usd: Usd
    predicted_usd: Usd
    package_url: str | None = None


class RunFailedPayload(_Api):
    error: ErrorBody
    partial: bool
    spent_usd: Usd


class ModeNoticePayload(_Api):
    notice: Literal["recorded_mode", "live_refused", "live_cap_warning"]
    mode: Mode
    refusal: RefusalReason | None = None
    detail: str


class RunStarted(_EventBase):
    type: Literal["run_started"] = "run_started"
    payload: RunStartedPayload


class AgentHired(_EventBase):
    type: Literal["agent_hired"] = "agent_hired"
    payload: AgentHiredPayload


class TaskAssigned(_EventBase):
    type: Literal["task_assigned"] = "task_assigned"
    payload: TaskAssignedPayload


class TaskStarted(_EventBase):
    type: Literal["task_started"] = "task_started"
    payload: TaskStartedPayload


class AttemptRecorded(_EventBase):
    type: Literal["attempt_recorded"] = "attempt_recorded"
    payload: AttemptRecordedPayload


class ToolCalled(_EventBase):
    type: Literal["tool_called"] = "tool_called"
    payload: ToolCalledPayload


class BudgetUpdate(_EventBase):
    type: Literal["budget_update"] = "budget_update"
    payload: BudgetUpdatePayload


class Message(_EventBase):
    type: Literal["message"] = "message"
    payload: MessagePayload


class TaskResult(_EventBase):
    type: Literal["task_result"] = "task_result"
    payload: TaskResultPayload


class AuditResult(_EventBase):
    type: Literal["audit_result"] = "audit_result"
    payload: AuditResultPayload


class RunFinished(_EventBase):
    type: Literal["run_finished"] = "run_finished"
    payload: RunFinishedPayload


class RunFailed(_EventBase):
    type: Literal["run_failed"] = "run_failed"
    payload: RunFailedPayload


class ModeNotice(_EventBase):
    type: Literal["mode_notice"] = "mode_notice"
    payload: ModeNoticePayload


SseEvent = Annotated[
    RunStarted
    | AgentHired
    | TaskAssigned
    | TaskStarted
    | AttemptRecorded
    | ToolCalled
    | BudgetUpdate
    | Message
    | TaskResult
    | AuditResult
    | RunFinished
    | RunFailed
    | ModeNotice,
    Field(discriminator="type"),
]
SSE_EVENT_ADAPTER: TypeAdapter[SseEvent] = TypeAdapter(SseEvent)
EVENT_TYPES = (
    "run_started",
    "agent_hired",
    "task_assigned",
    "task_started",
    "attempt_recorded",
    "tool_called",
    "budget_update",
    "message",
    "task_result",
    "audit_result",
    "run_finished",
    "run_failed",
    "mode_notice",
)
TERMINAL_EVENTS = ("run_finished", "run_failed")

# Every top-level payload, by schema file name (docs/api/schemas/<name>.json).
SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "ErrorResponse": ErrorResponse,
    "ModesView": ModesView,
    "CreateRunRequest": CreateRunRequest,
    "RunView": RunView,
    "RunList": RunList,
    "ApprovalRequest": ApprovalRequest,
    "OrgChart": OrgChart,
    "LedgerView": LedgerView,
    "ChatMessageList": ChatMessageList,
    "PostMessageRequest": PostMessageRequest,
    "TaskList": TaskList,
    "DeliveryPackage": DeliveryPackage,
}
