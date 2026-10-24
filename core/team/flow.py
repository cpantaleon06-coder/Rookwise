"""The team hierarchy: director -> managers -> operators -> auditor.

Built only on the harness and the runner. Every model call goes through
`rookwise.harness`: the director, managers and auditor through `run_with_escalation`
with no tools (`rookwise.team.agents`), operators through `rookwise.runner.run_operator`.
The ledger, rate limits, retries, repairs and the escalation ladder therefore apply to
every call. Roles, models and skills are data (`rookwise.team.config`); the tasks come
from the director's plan, so nothing here depends on a domain.

Slices: every source of the bundle is cut into slices (`rookwise.slicing`, config/
slicing.json). The director's plan gives each task a role and the source it reads, and
must read every non-empty source (`plan_model`, a repairable validation error otherwise),
so the plan covers every slice. Each slice of a task's source then goes to its own
operator task: the slice is stored at `slice_ref` and is the task's only input, so the
operator reads that slice and nothing else. Citations are still validated against the
full sources (`findings_model`). `TeamRun.unread_slices` lists the line ranges that no
completed operator task read (for example because the budget ran out), computed with
`rookwise.slicing.coverage`.

Flow and budget, through the ledger's allocations (`rookwise.ledger`):
1. The director reads the run budget from the ledger and makes the plan call, drawn from
   the run itself.
2. It hires the auditor and allocates its share, keeps the director's share free in the
   run for its diagnosis, and hires one manager per block. The blocks run from the
   smallest estimated need to the largest, each allocated just before it runs by max-min
   fairness: the smaller of its need and an equal share of what the run has left for the
   remaining blocks, and the rest for the last one (`BudgetPolicy`, config/budget.json).
   Money a block leaves unspent goes back to the run when it closes, so later blocks can
   use it.
3. A manager keeps its own share of the block and puts the rest in the block's operator
   pool, a ledger allocation every operator of the block reserves from. Money is held only
   while a call is in flight, so operators running one after another hold one
   reservation at a time; the ledger refuses a reservation the pool (or the run) cannot
   cover. A task may spend at most 3 times its first reservation plus 1 time the same
   request's reservation one rung up the model ladder (both in config/budget.json),
   across its attempts and its reassignment, as the ledger's task cap (money spent,
   nothing carved out of the pool). At start, a run whose slices plus the operator prompt
   could pass `operator_max_input_tokens` is refused (`ConfigError`), so no task would
   stop on its token ceiling before its first call. When the block's tasks are done the
   pool is closed and what is left goes back to the manager. How a failed task goes on
   depends on why it stopped:
   - a task ceiling (`length` or `token_ceiling`: this one task hit its own output
     ceiling or token budget) gets at most one reassignment: to the next catalog
     operator for the role, or, when none is left, to the same operator one rung up the
     model ladder (`escalation.next`, config/harness.json);
   - a ledger stop (`budget_exhausted`: the ledger refused a reservation, so a budget
     scope is spent) ends that scope: the task is not reassigned, and `budget_exhausted`
     is emitted as before;
   - any other failure is reassigned to the next catalog operator, up to
     `max_reassignments` times.
   With no reassignment left, the task is escalated to the director.
4. The manager consolidates inside its allocation, then closes it; the unspent part goes
   back to the run. Managers and the director receive only the findings that carry
   claims (the claims with their citations and the store ref of each finding), plus
   counts of slices read, slices with no claims and tasks not done; a finding without
   claims is stored but only counted. When a manager's estimated input passes
   `manager_max_input_tokens`, it consolidates in batches, one call each
   (`BlockOutcome.batches`).
5. The director writes the diagnosis (`Diagnosis`, validated by `diagnosis_model` for
   shape only), drawn from the run. It receives the context sources in full
   (`context_sources`, for example the ticket and the runbook), the source inventory, and
   the managers' summaries and the operators' findings under their store references, and
   it may cite evidence lines directly. A bad quote does not reject its reply: the
   deterministic check withdraws the claim (D3). If every root-cause claim is withdrawn,
   the director gets exactly one targeted repair request that lists those claims with
   their reason codes and the lines they cite (ledger task `diagnosis-repair`).
6. Decision D3 (`rookwise.team.auditor`): the deterministic check runs on the diagnosis's
   claims; unsupported claims are withdrawn and listed with their reason codes. With no
   supported root-cause claim the diagnosis is inconclusive and the auditor makes no model
   call; otherwise the auditor model reviews the supported claims, the withdrawn list and
   its rubric. The operators' own claims are checked too, for the report
   (`TeamRun.operator_evidence`).

A level that runs out of budget does not raise: it emits `budget_exhausted` with the
ledger's stop, then the director: `run_failed` with code `budget_exhausted` and the stop
in `details`. A manager: its block is partial, the director says so in a `message`, and
`run_finished` has `partial: true`. An operator: `task_result` with status `failed`. The
auditor: `audit_result` with `accepted_with_warning`. Each case is also in
`TeamRun.notes`.

Events follow the API contract's documented order; the events of one agent call are
emitted when that call returns. Every ledger `allocate` and `close` emits
`budget_allocation`, after the agent is hired. Every reassignment and every escalation to
the director emits `escalation`.

Not built: the user's approval of the plan (it is shown in a director message and runs at
once), parallel managers and operators, the auditor's correction cycle, one `tool_called`
event per tool call, cancellation and reputation updates.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from rookwise.api.models import (
    AgentHiredPayload,
    AgentNode,
    AllocationAction,
    AuditResultPayload,
    AuditVerdict,
    BudgetAllocationPayload,
    BudgetExhaustedPayload,
    ChatMessage,
    ErrorBody,
    EscalationPayload,
    MessagePayload,
    Mode,
    RunFailedPayload,
    RunFinishedPayload,
    RunStartedPayload,
    SseEvent,
    TaskAssignedPayload,
    TaskResultPayload,
)
from rookwise.evidence import EvidenceBundle, EvidenceReport, split_lines, verify
from rookwise.harness import ConfigError, Harness, Tool
from rookwise.harness.config import HarnessConfig
from rookwise.harness.loop import prepare_messages
from rookwise.harness.request import (
    BuiltRequest,
    ChatRequest,
    JsonObjectFormat,
    JsonSchemaFormat,
    build_request,
)
from rookwise.harness.salvage import Salvage, salvage_json
from rookwise.harness.schema import inline_refs
from rookwise.harness.validate import final_result_instructions, payload_model
from rookwise.ledger import Allocation, CapReached, RunReport
from rookwise.money import ZERO_USD, format_usd, to_micro_usd
from rookwise.runner import DEFAULT_BASE_PROMPT, OperatorSpec, run_operator
from rookwise.schemas import Level, TaskV1
from rookwise.skills import compose_system_prompt, role_max_output_tokens
from rookwise.skills.loader import SKILLS_DIR
from rookwise.slicing import (
    Slice,
    SlicingConfig,
    coverage,
    load_slicing_config,
    numbered_line,
    slice_bundle,
)
from rookwise.store import Store
from rookwise.team.agents import AgentCaller
from rookwise.team.auditor import (
    ClaimCounts,
    DiagnosisStatus,
    WithdrawnClaim,
    audit,
    render_source,
    split_claims,
)
from rookwise.team.config import BudgetPolicy, RoleSpec, load_budget_policy, load_team_roles
from rookwise.team.events import EventLog
from rookwise.team.models import (
    BlockSummary,
    CitationLog,
    Diagnosis,
    FindingClaim,
    Findings,
    Plan,
    PlanBlock,
    PlanTask,
    ReplyCitations,
    SliceAssignment,
    diagnosis_model,
    findings_model,
    plan_model,
)

DIRECTOR_PROMPT = (
    "You are the director of a team of AI agents. Split the goal into blocks of work, one "
    "per manager, and each block into tasks for operators. Each task names an operator role "
    "and the one source it reads, and every source must be read by at least one task. Use "
    "only the operator roles and source ids you are given. Keep to the required final "
    "result format. Its shape, with placeholders in angle brackets and one block and one "
    "task shown (the JSON Schema below is the rule):\n"
    '{"status": "ok", "output": {"summary": "<the plan in one paragraph>", "blocks": '
    '[{"goal": "<the goal of the block>", "tasks": [{"role": "<an operator role>", '
    '"source_id": "<a source id>", "instruction": "<what to look for>"}]}]}, "notes": ""}\n'
    '"summary" and "blocks" go inside "output"; "notes" comes after "output" is closed, at '
    "the top level."
)
DIAGNOSIS_PROMPT = (
    "You are the director of a team of AI agents, and the investigation is done. Write the "
    "diagnosis from your managers' consolidated findings and the evidence: the root cause, "
    "its category, the claims that support it, each backed by citations, and a remediation "
    "plan. Each citation is one source_id, a line_start and a line_end, and a quote copied "
    "verbatim from one single line of that range, including its timestamp; never join "
    "lines. The remediation plan is a proposal for a human to approve: nothing in it is "
    "executed. Keep to the required final result format."
)
MANAGER_PROMPT = (
    "You are a manager in a team of AI agents. Consolidate your operators' results into one "
    "short summary of your block. Keep to the required final result format."
)
OPERATOR_PROMPT = (
    f"{DEFAULT_BASE_PROMPT} Back every claim with citations. A citation has exactly four "
    "fields: source_id, line_start, line_end and quote. The quote is copied verbatim from "
    "one single line between line_start and line_end, including its timestamp, and never "
    'includes the line-number prefix (the "12: " before each line). To support a claim '
    "with several lines, give several citations, one per line, with line_start equal to "
    'line_end. Never join lines in one quote, with a line break, " | " or anything else. '
    "When the same kind of line repeats, cite its first and last occurrence and any line "
    "that shows a different cause; never cite every matching line."
)


def operator_prompt(policy: BudgetPolicy) -> str:
    """`OPERATOR_PROMPT` with the reply caps of `policy` (config/budget.json)."""
    return (
        f"{OPERATOR_PROMPT} Report at most {policy.operator_max_claims} claims, each with "
        f"at most {policy.operator_max_citations_per_claim} citations."
    )


# Why an operator stopped. A task ceiling is this one task hitting its own cap (its
# output ceiling or its token budget); a ledger stop is the ledger refusing a reservation.
TASK_CEILING_STOPS = ("length", "token_ceiling")
LEDGER_STOPS = ("budget_exhausted",)

TaskStatus = Literal["ok", "failed", "not_run"]
BlockStatus = Literal["ok", "partial", "failed"]


@dataclass
class TaskOutcome:
    """One operator task: one slice for one plan task's role. `assignments` holds the
    task_v1 ids, one per operator tried."""

    task_id: str
    role: str
    slice: Slice
    status: TaskStatus = "not_run"
    assignments: list[str] = field(default_factory=list)
    operator_ids: list[str] = field(default_factory=list)
    findings: Findings | None = None
    reason: str = ""


@dataclass
class BlockOutcome:
    block_id: str
    agent_id: str
    goal: str
    status: BlockStatus
    tasks: list[TaskOutcome]
    summary: str | None
    allocated_usd: Decimal
    released_usd: Decimal
    reason: str = ""
    batches: int = 0  # the manager's consolidation calls (0 when it made none)
    slices_read: int = 0  # completed operator tasks
    empty_slices: int = 0  # completed operator tasks whose finding has no claim
    not_done: int = 0


@dataclass(frozen=True)
class UnreadRange:
    """Lines of a source that no completed operator task read."""

    source_id: str
    line_start: int
    line_end: int


@dataclass
class TeamRun:
    run_id: str
    # "cancelled": the caller stopped the run on purpose (`stop_after`).
    status: Literal["finished", "failed", "cancelled"]
    partial: bool
    plan: Plan | None
    blocks: list[BlockOutcome]
    audit: AuditVerdict | None
    evidence: EvidenceReport | None
    notes: list[str]
    events: list[SseEvent]
    report: RunReport
    unread_slices: list[UnreadRange] = field(default_factory=list)
    empty_sources: list[str] = field(default_factory=list)
    diagnosis: Diagnosis | None = None
    # D3: the diagnosis's status, its supported and withdrawn claims and their counts.
    diagnosis_status: DiagnosisStatus | None = None
    inconclusive_reason: str = ""
    supported_claims: list[FindingClaim] = field(default_factory=list)
    withdrawn_claims: list[WithdrawnClaim] = field(default_factory=list)
    claim_counts: ClaimCounts | None = None
    # The deterministic check of the operators' claims (`evidence` is the diagnosis's).
    operator_evidence: EvidenceReport | None = None
    # Per-citation results of every validated reply, by task id (first reply: index 0).
    citation_log: list[ReplyCitations] = field(default_factory=list)
    # The director's first diagnosis and whether the one targeted repair was asked for.
    first_diagnosis: Diagnosis | None = None
    diagnosis_repairs: int = 0
    # Each operator task's estimated first reservation and its spending limit.
    first_reservations: dict[str, Decimal] = field(default_factory=dict)
    task_limits: dict[str, Decimal] = field(default_factory=dict)
    # Each operator task's estimated reservation of one retry with history (zero when off).
    retry_reservations: dict[str, Decimal] = field(default_factory=dict)
    # Operator replies salvaged from a cut or broken reply, by task id: the trailing
    # elements each salvage dropped.
    salvaged_replies: dict[str, list[int]] = field(default_factory=dict)
    # Operator citations whose source_id was derived from the assigned slice, by task id.
    citation_source_normalizations: dict[str, int] = field(default_factory=dict)


def summary_ref(run_id: str, block_id: str) -> str:
    return f"store://{run_id}/summaries/{block_id}"


def slice_ref(run_id: str, item: Slice) -> str:
    return f"store://{run_id}/slices/{item.slice_id}"


def source_ref(run_id: str, source_id: str) -> str:
    return f"store://{run_id}/sources/{source_id}"


def brief_ref(run_id: str, task_id: str) -> str:
    return f"store://{run_id}/briefs/{task_id}"


def _floor(value: Decimal) -> Decimal:
    return to_micro_usd(value, ROUND_FLOOR)


def _fair_share(available: Decimal, need: Decimal, remaining: int) -> Decimal:
    """Max-min fairness, one block at a time from the smallest need: the smaller of the
    block's need and an equal share of what is left for the `remaining` blocks; the last
    block gets all that is left. Rounded down, so it never passes `available`."""
    if remaining <= 1:
        return _floor(available)
    return _floor(min(need, available / remaining))


def _finding_entry(run_id: str, task: TaskOutcome) -> str:
    """A finding with claims as managers and the director read it: its store ref, the
    task and its slice, then its claims with their citations."""
    ref = f"store://{run_id}/results/{task.assignments[-1]}"
    claims = json.dumps([c.model_dump() for c in task.findings.claims], ensure_ascii=False)
    return f"[{ref}] {task.task_id} ({task.role}, {task.slice.slice_id}):\n{claims}"


def _counts_header(goal: str, outcomes: list[TaskOutcome]) -> str:
    done = [t for t in outcomes if t.status == "ok"]
    empty = sum(not t.findings.claims for t in done)
    lines = [
        f"Block goal: {goal}",
        f"Slices read: {len(done)}, of which {empty} with no claims; not done: "
        f"{len(outcomes) - len(done)}.",
    ]
    lines += [
        f"- not done: {t.task_id} ({t.role}, {t.slice.slice_id}). {t.reason}"
        for t in outcomes
        if t.status != "ok"
    ]
    return "\n".join(lines)


def _consolidation_request(header: str, entries: list[str], number: int, total: int) -> str:
    part = f"\n\nBatch {number} of {total} of this block's findings." if total > 1 else ""
    findings = "\n".join(entries) or "(no finding with claims)"
    return f"{header}{part}\n\nFindings with claims, by reference:\n{findings}"


def retry_request(first: BuiltRequest, policy: BudgetPolicy, config: HarnessConfig) -> BuiltRequest:
    """One retry of `first` (a repair or a re-prompt), as the harness would build it: the
    same request with the reply in its history, sized as the whole output ceiling at
    `retry_reply_chars_per_token`, then `retry_feedback_chars` of feedback. It goes through
    the same estimate the harness reserves with."""
    reply = math.ceil(first.max_tokens * policy.retry_reply_chars_per_token)
    history = [
        *first.request.messages,
        {"role": "assistant", "content": "x" * reply},
        {"role": "user", "content": "x" * policy.retry_feedback_chars},
    ]
    return build_request(replace(first.request, messages=history), config)


def _brief(task: PlanTask, item: Slice) -> str:
    return (
        f"{task.instruction}\n\nRead only the slice you are given: {item.source_id}, "
        f"lines {item.line_start}-{item.line_end} of {item.line_count}."
    )


async def run_team(
    goal: str,
    *,
    run_id: str,
    harness: Harness,
    store: Store,
    catalog: Sequence[OperatorSpec],
    evidence: EvidenceBundle,
    skills_config: dict[str, Any] | None = None,
    skills_dir: Path = SKILLS_DIR,
    policy: BudgetPolicy | None = None,
    tools: Mapping[str, Tool] | None = None,
    mode: Mode = "live",
    simulated_case: bool = True,
    clock: Callable[[], datetime] | None = None,
    slicing: SlicingConfig | None = None,
    context_sources: Sequence[str] = (),
    stop_after: Literal["plan"] | None = None,
) -> TeamRun:
    """Run the hierarchy for one goal. The run must already be open in the harness's
    ledger (the administrator layer opens it with the run cap). `slicing` defaults to
    config/slicing.json. `context_sources` are the source ids the director reads in full
    for its diagnosis (for example the ticket and the runbook). `stop_after="plan"` ends
    the run once the director's plan is valid, before any allocation or other call: it
    finishes as `cancelled` and partial, and costs only the plan call (with its re-prompts,
    repairs and escalations)."""
    unknown = [s for s in context_sources if s not in evidence.sources]
    if unknown:
        raise ValueError(f"context sources not in the evidence bundle: {unknown}")
    team = _Team(
        run_id=run_id,
        harness=harness,
        store=store,
        catalog=catalog,
        evidence=evidence,
        skills_config=skills_config,
        skills_dir=skills_dir,
        policy=policy or load_budget_policy(),
        tools=tools or {},
        log=EventLog(run_id, mode=mode, clock=clock),
        simulated_case=simulated_case,
        slicing=slicing or load_slicing_config(),
        context_sources=tuple(context_sources),
        stop_after=stop_after,
    )
    return await team.run(goal)


class _Team:
    def __init__(
        self,
        *,
        run_id: str,
        harness: Harness,
        store: Store,
        catalog: Sequence[OperatorSpec],
        evidence: EvidenceBundle,
        skills_config: dict[str, Any] | None,
        skills_dir: Path,
        policy: BudgetPolicy,
        tools: Mapping[str, Tool],
        log: EventLog,
        simulated_case: bool,
        slicing: SlicingConfig,
        context_sources: tuple[str, ...] = (),
        stop_after: Literal["plan"] | None = None,
    ) -> None:
        self.run_id = run_id
        self.stop_after = stop_after
        self.harness = harness
        self.ledger = harness.ledger
        self.store = store
        self.catalog = list(catalog)
        self.evidence = evidence
        self.skills_config = skills_config
        self.skills_dir = skills_dir
        self.policy = policy
        self.tools = tools
        self.log = log
        self.simulated_case = simulated_case
        self.roles = load_team_roles(skills_config)
        self.caller = AgentCaller(harness, log, skills_config=skills_config, skills_dir=skills_dir)
        # The operators' output model checks every quote against this run's full sources.
        # Per-citation results of every reply, for the run report (`TeamRun.citation_log`).
        self.citation_log = CitationLog()
        # The slice of the operator call in progress: citations take their source from it.
        self.slice_assignment = SliceAssignment()
        self.findings_model = findings_model(
            evidence,
            self.citation_log,
            self.slice_assignment,
            max_claims=self.policy.operator_max_claims,
            max_citations_per_claim=self.policy.operator_max_citations_per_claim,
        )
        self.operator_prompt = operator_prompt(self.policy)
        self.diagnosis_model = diagnosis_model(evidence, self.citation_log)
        self.context_sources = context_sources
        self.slices = slice_bundle(evidence.sources, slicing)
        self.slices_of: dict[str, list[Slice]] = {source_id: [] for source_id in evidence.sources}
        for item in self.slices.slices:
            self.slices_of[item.source_id].append(item)
        self.plan_model = plan_model(
            list(evidence.sources), [s for s, items in self.slices_of.items() if items]
        )
        self.notes: list[str] = []
        self.plan: Plan | None = None
        self.systems: dict[str, str] = {}  # operator system prompts by role, for estimates
        self.first_reservation: dict[str, Decimal] = {}  # by operator task id
        self.expected_cost: dict[str, Decimal] = {}  # by operator task id
        self.task_limit: dict[str, Decimal] = {}  # by operator task id
        self.retry_reservation: dict[str, Decimal] = {}  # by operator task id
        # Each operator task's first request: (input token estimate, output ceiling).
        self.first_request: dict[str, tuple[int, int]] = {}
        # Operator replies salvaged from a cut or broken reply: the elements each dropped.
        self.salvaged: dict[str, list[int]] = {}
        self.manager_reservation: Decimal | None = None
        self._check_config(slicing)

    # -- director ------------------------------------------------------------------------

    async def run(self, goal: str) -> TeamRun:
        cap = self.ledger.report(self.run_id).caps.run_usd
        if cap <= 0:
            raise ValueError(f"run {self.run_id} has no budget")
        self.log.emit(
            "run_started",
            RunStartedPayload(
                goal=goal,
                mode=self.log.mode,
                budget_usd=cap,
                board=False,
                simulated_case=self.simulated_case,
            ),
        )
        director = self._hire("a-director", self.roles.director, None)
        for item in self.slices.slices:
            self.store.put(slice_ref(self.run_id, item), item.text)

        result = await self.caller.call(
            director,
            self.roles.director,
            level="director",
            task_id="plan",
            base_prompt=DIRECTOR_PROMPT,
            user=self._plan_request(goal),
            output_model=self.plan_model,
            budget_id=None,
            response_format=self._plan_format(),
        )
        if not result.ok or result.validation is None:
            if result.stop_reason == "budget_exhausted":
                self.notes.append("The run budget does not cover the director's plan call.")
                stop = self._stop_of("director", "plan", None)
                return self._fail_on_budget(director, stop, self.notes[-1])
            return self._fail(
                "plan_failed",
                f"The director produced no valid plan ({result.stop_reason}).",
                {"level": "director", "stop_reason": result.stop_reason},
            )
        plan: Plan = result.validation.payload.output  # type: ignore[attr-defined]
        self.plan = plan
        limits = (self.policy.max_blocks, self.policy.max_tasks_per_block)
        if len(plan.blocks) > limits[0] or any(len(b.tasks) > limits[1] for b in plan.blocks):
            return self._fail(
                "plan_too_large",
                f"The plan has more than {limits[0]} blocks or {limits[1]} tasks in a block.",
                {"max_blocks": limits[0], "max_tasks_per_block": limits[1]},
            )
        tasks = sum(len(block.tasks) for block in plan.blocks)
        work = sum(len(self.slices_of[t.source_id]) for b in plan.blocks for t in b.tasks)
        self._say(f"{plan.summary} ({len(plan.blocks)} blocks, {tasks} tasks over {work} slices.)")

        stops = self.ledger.report(self.run_id).stops
        run_stop = next((s for s in stops if s.scope == "run"), None)
        if run_stop is not None:  # the plan call ran over the run cap, which stopped the run
            self.notes.append("The run budget was used up by the director's plan call.")
            return self._fail_on_budget(director, run_stop, self.notes[-1])
        if self.stop_after == "plan":
            self.notes.append(
                "Stopped after the director's plan, as asked: no manager, operator, auditor "
                "or diagnosis call ran."
            )
            return self._stopped(plan)
        # Every agent is hired before its allocation, so its budget_allocation event can
        # name it. The amounts fit what is free, so no allocation here is refused.
        auditor = self._hire("a-auditor", self.roles.auditor, None)
        free = self.ledger.free(self.run_id)
        auditor_share = _floor(free * self.policy.auditor_share)
        auditor_budget = self._allocate(auditor, director, "budget:auditor", auditor_share)
        director_share = _floor(free * self.policy.director_share)  # stays in the run
        work_items: list[list[tuple[str, PlanTask, Slice]]] = []
        number = 0
        for block in plan.blocks:
            items: list[tuple[str, PlanTask, Slice]] = []
            for task in block.tasks:
                for item in self.slices_of[task.source_id]:
                    number += 1
                    task_id = f"t-{number}"
                    items.append((task_id, task, item))
                    reservation, expected, next_rung, retry = self._estimate(task, item, task_id)
                    self.first_reservation[task_id] = reservation
                    self.expected_cost[task_id] = expected
                    self.retry_reservation[task_id] = retry
                    self.task_limit[task_id] = _floor(
                        reservation * self.policy.task_limit_first_rung_reservations
                        + next_rung * self.policy.task_limit_next_rung_reservations
                    )
            work_items.append(items)
        needs = [self._block_need(items) for items in work_items]
        managers = [
            self._hire(f"a-manager-b-{index}", self.roles.manager, director.agent_id)
            for index in range(1, len(plan.blocks) + 1)
        ]
        order = sorted(range(len(plan.blocks)), key=lambda i: (needs[i], i))
        outcomes: dict[int, BlockOutcome] = {}
        for position, index in enumerate(order):
            available = max(self.ledger.free(self.run_id) - director_share, ZERO_USD)
            amount = _fair_share(available, needs[index], len(order) - position)
            manager = managers[index]
            budget = self._allocate(manager, director, f"budget:b-{index + 1}", amount)
            outcomes[index] = await self._manage(
                f"b-{index + 1}", plan.blocks[index], budget, work_items[index], manager, director
            )
        blocks = [outcomes[index] for index in range(len(plan.blocks))]  # in plan order

        diagnosis, missing = await self._diagnose(goal, director, blocks)
        first_diagnosis, repairs = diagnosis, 0
        if diagnosis is not None and self._root_withdrawn(diagnosis):
            repairs = 1
            diagnosis = await self._repair_diagnosis(goal, director, diagnosis) or diagnosis

        operator_claims = [
            c.claim(f"{t.task_id}:{c.claim_id}")
            for b in blocks
            for t in b.tasks
            if t.findings is not None
            for c in t.findings.claims
        ]
        operator_evidence = verify(self.evidence, operator_claims)
        outcome = await audit(
            self.caller,
            auditor,
            self.roles.auditor,
            goal=goal,
            diagnosis=diagnosis,
            bundle=self.evidence,
            budget_id=auditor_budget.id,
            missing_reason=missing,
        )
        if outcome.budget_exhausted:
            self._exhausted(auditor, self._stop_of("auditor", "audit", auditor_budget.id))
            self.notes.append("The auditor ran out of budget: only the deterministic check ran.")
        self.log.emit("audit_result", AuditResultPayload(audit=outcome.verdict))
        self._close(auditor_budget, auditor, director)
        partial = outcome.budget_exhausted or any(b.status != "ok" for b in blocks)
        self._say(self._closing_message(blocks, outcome))
        report = self.ledger.report(self.run_id)
        self.log.emit(
            "run_finished",
            RunFinishedPayload(
                status="finished",
                partial=partial,
                spent_usd=report.spent_usd,
                predicted_usd=sum((e.usd_predicted for e in report.entries), ZERO_USD),
                package_url=None,
            ),
        )
        return TeamRun(
            run_id=self.run_id,
            status="finished",
            partial=partial,
            plan=plan,
            blocks=blocks,
            audit=outcome.verdict,
            evidence=outcome.evidence,
            notes=self.notes,
            events=self.log.events,
            report=report,
            unread_slices=self._unread(blocks),
            empty_sources=list(self.slices.empty_sources),
            diagnosis=diagnosis,
            diagnosis_status=outcome.status,
            inconclusive_reason=outcome.reason,
            supported_claims=list(outcome.supported),
            withdrawn_claims=list(outcome.withdrawn),
            claim_counts=outcome.counts,
            operator_evidence=operator_evidence,
            citation_log=list(self.citation_log.replies),
            first_diagnosis=first_diagnosis,
            diagnosis_repairs=repairs,
            first_reservations=dict(self.first_reservation),
            task_limits=dict(self.task_limit),
            retry_reservations=dict(self.retry_reservation),
            salvaged_replies={k: list(v) for k, v in self.salvaged.items()},
            citation_source_normalizations={
                k: v for k, v in self.slice_assignment.by_task.items() if v
            },
        )

    async def _diagnose(
        self, goal: str, director: AgentNode, blocks: list[BlockOutcome]
    ) -> tuple[Diagnosis | None, str]:
        """The director's diagnosis call, drawn from the run, and why it is missing."""
        self.citation_log.task_id = "diagnosis"
        result = await self.caller.call(
            director,
            self.roles.director,
            level="director",
            task_id="diagnosis",
            base_prompt=DIAGNOSIS_PROMPT,
            user=self._diagnosis_request(goal, blocks),
            output_model=self.diagnosis_model,
            budget_id=None,
        )
        if result.ok and result.validation is not None:
            return result.validation.payload.output, ""  # type: ignore[attr-defined]
        if result.stop_reason == "budget_exhausted":
            self._exhausted(director, self._stop_of("director", "diagnosis", None))
            reason = "the run budget does not cover the director's diagnosis call"
        else:
            reason = f"the director produced no valid diagnosis ({result.stop_reason})"
        self.notes.append(reason[0].upper() + reason[1:] + ".")
        return None, reason

    def _root_withdrawn(self, diagnosis: Diagnosis) -> bool:
        split = split_claims(diagnosis, self.evidence)
        withdrawn = {w.claim.claim_id for w in split.withdrawn}
        return all(claim_id in withdrawn for claim_id in diagnosis.root_cause_claim_ids)

    async def _repair_diagnosis(
        self, goal: str, director: AgentNode, diagnosis: Diagnosis
    ) -> Diagnosis | None:
        """The one targeted repair: every root-cause claim was withdrawn. The reply is
        logged as the diagnosis's second reply. None when the call fails."""
        split = split_claims(diagnosis, self.evidence)
        results = {r.claim_id: r for r in split.report.claims}
        root = set(diagnosis.root_cause_claim_ids)
        listed, cited = [], []
        for withdrawn in split.withdrawn:
            if withdrawn.claim.claim_id not in root:
                continue
            result = results[withdrawn.claim.claim_id]
            reasons = "; ".join(
                f"citation {c.index}: {c.reason}" + (f" ({c.detail})" if c.detail else "")
                for c in result.citations
            )
            listed.append(f"- {withdrawn.claim.claim_id}: {withdrawn.reason}. {reasons}".rstrip())
            cited += self._lines_near(withdrawn.claim)
        self.notes.append(
            "Every root-cause claim of the diagnosis was withdrawn; the director gets one "
            "targeted repair request."
        )
        user = (
            f"Goal: {goal}\n\nThe deterministic evidence check withdrew every claim your "
            "root cause rests on:\n" + "\n".join(listed) + "\n\nThe lines around what they "
            "cite:\n"
            + ("\n\n".join(cited) or "(none)")
            + "\n\nYour diagnosis:\n"
            + diagnosis.model_dump_json()
            + "\n\nReply with the whole diagnosis again, with corrected citations for these "
            "claims: each quote copied verbatim from one single line of its range, "
            "including its timestamp. Keep the claims that were supported."
        )
        self.citation_log.task_id = "diagnosis"
        result = await self.caller.call(
            director,
            self.roles.director,
            level="director",
            task_id="diagnosis-repair",
            base_prompt=DIAGNOSIS_PROMPT,
            user=user,
            output_model=self.diagnosis_model,
            budget_id=None,
        )
        if result.ok and result.validation is not None:
            return result.validation.payload.output  # type: ignore[attr-defined]
        if result.stop_reason == "budget_exhausted":
            self._exhausted(director, self._stop_of("director", "diagnosis-repair", None))
        self.notes.append(f"The diagnosis repair produced no valid reply ({result.stop_reason}).")
        return None

    def _lines_near(self, claim: FindingClaim, context: int = 5) -> list[str]:
        """The source lines around each citation of `claim`, as agents read them."""
        parts = []
        for citation in claim.citations:
            text = self.evidence.sources.get(citation.source_id)
            if text is None:
                parts.append(
                    f"There is no source {citation.source_id!r}; the sources are "
                    + ", ".join(self.evidence.sources)
                    + "."
                )
                continue
            lines = split_lines(text)
            first = min(max(citation.line_start - context, 1), max(len(lines), 1))
            last = min(max(citation.line_end, citation.line_start) + context, len(lines))
            shown = "\n".join(numbered_line(n, lines[n - 1]) for n in range(first, last + 1))
            parts.append(f"Source {citation.source_id}, lines {first}-{last}:\n{shown}")
        return parts

    def _diagnosis_request(self, goal: str, blocks: list[BlockOutcome]) -> str:
        parts = [f"Goal: {goal}"]
        if self.context_sources:
            parts.append("Context, read in full:")
            parts += [render_source(s, self.evidence.sources[s]) for s in self.context_sources]
        inventory = [
            f"- {source_id}: {self.slices.line_counts[source_id]} lines, {len(items)} slices"
            for source_id, items in self.slices_of.items()
        ]
        parts.append("Sources and their slices:\n" + ("\n".join(inventory) or "none"))
        findings = ["Managers' consolidated findings, by reference (only findings with claims):"]
        for block in blocks:
            findings.append(
                f"[{summary_ref(self.run_id, block.block_id)}]\nBlock {block.block_id}: "
                f"{block.goal}\nSummary: {block.summary or '(none)'}\n"
                f"Slices read: {block.slices_read}, of which {block.empty_slices} with no "
                f"claims; not done: {block.not_done}."
            )
            findings += [
                _finding_entry(self.run_id, t)
                for t in block.tasks
                if t.findings is not None and t.findings.claims
            ]
        parts.append("\n".join(findings))
        unread = self._unread(blocks)
        if unread:
            ranges = ", ".join(f"{u.source_id} {u.line_start}-{u.line_end}" for u in unread)
            parts.append(f"Lines no operator read: {ranges}.")
        parts.append(
            "Write the diagnosis. Back every claim with citations; you may cite evidence lines "
            "directly, from the context above or from the operators' citations. "
            "root_cause_claim_ids lists the claims the root cause rests on."
        )
        return "\n\n".join(parts)

    # -- manager -------------------------------------------------------------------------

    async def _manage(
        self,
        block_id: str,
        block: PlanBlock,
        budget: Allocation,
        items: list[tuple[str, PlanTask, Slice]],
        manager: AgentNode,
        director: AgentNode,
    ) -> BlockOutcome:
        own = self._manager_keeps(budget.usd)
        outcomes = []
        if items:
            pool = self._allocate(
                manager, manager, f"pool:{block_id}", budget.usd - own, parent=budget.id
            )
            for task_id, task, item in items:
                outcomes.append(await self._staff(task_id, task, item, manager, director, pool))
            self._close(pool, manager, manager)
        done = [t for t in outcomes if t.status == "ok"]
        summary, reason, batches = None, "", []
        if not done:
            reason = f"Block {block_id} has no completed task; escalated to the director."
            self._escalate(manager, director, None, reason)
        else:
            header = _counts_header(block.goal, outcomes)
            batches = self._batches(
                header, [_finding_entry(self.run_id, t) for t in done if t.findings.claims]
            )
            summaries = []
            for number, batch in enumerate(batches, 1):
                summary_id = (
                    f"{block_id}-summary" if len(batches) == 1 else f"{block_id}-summary-{number}"
                )
                result = await self.caller.call(
                    manager,
                    self.roles.manager,
                    level="manager",
                    task_id=summary_id,
                    base_prompt=MANAGER_PROMPT,
                    user=_consolidation_request(header, batch, number, len(batches)),
                    output_model=BlockSummary,
                    budget_id=budget.id,
                )
                if result.ok and result.validation is not None:
                    summaries.append(result.validation.payload.output.summary)  # type: ignore[attr-defined]
                    continue
                if result.stop_reason == "budget_exhausted":
                    reason = f"Manager {block_id} ran out of budget before its consolidation call."
                    self._exhausted(manager, self._stop_of("manager", summary_id, budget.id))
                else:
                    reason = (
                        f"Manager {block_id} could not consolidate ({result.stop_reason}); "
                        "escalated to the director."
                    )
                    self._escalate(manager, director, summary_id, reason)
                break
            if summaries:
                summary = "\n".join(summaries)
                self.store.put(summary_ref(self.run_id, block_id), summary)
        if reason:
            self.notes.append(reason)
        released = self._close(budget, manager, director)
        if not done:
            status: BlockStatus = "failed"
        elif len(done) == len(outcomes) and summary is not None and not reason:
            status = "ok"
        else:
            status = "partial"
        return BlockOutcome(
            block_id=block_id,
            agent_id=manager.agent_id,
            goal=block.goal,
            status=status,
            tasks=outcomes,
            summary=summary,
            allocated_usd=budget.usd,
            released_usd=released,
            reason=reason,
            batches=len(batches) if done else 0,
            slices_read=len(done),
            empty_slices=sum(not t.findings.claims for t in done),
            not_done=len(outcomes) - len(done),
        )

    async def _staff(
        self,
        task_id: str,
        task: PlanTask,
        item: Slice,
        manager: AgentNode,
        director: AgentNode,
        pool: Allocation,
    ) -> TaskOutcome:
        outcome = TaskOutcome(task_id=task_id, role=task.role, slice=item)
        failed: tuple[AgentNode, str, str] | None = None  # operator, task_v1 id, reason
        candidates = sorted(
            (spec for spec in self.catalog if spec.role == task.role),
            key=lambda spec: (spec.price_per_task_est_usd, -spec.reputation, spec.operator_id),
        )
        if not candidates:
            outcome.reason = f"{task_id}: no operator in the catalog for role {task.role}."
            self.notes.append(outcome.reason)
            return outcome
        self.store.put(brief_ref(self.run_id, task_id), _brief(task, item))
        limit = self.task_limit[task_id]
        spent = ZERO_USD
        spec: OperatorSpec | None = candidates[0]
        tried: list[OperatorSpec] = []
        reassignments, ceiling_reassignments = 0, 0
        number = 0
        while spec is not None:
            number += 1
            tried.append(spec)
            assignment = task_id if number == 1 else f"{task_id}.{number}"
            left = limit - spent  # the task's limit, counted as money spent
            if left <= 0:
                outcome.reason = f"{task_id}: the task has spent its limit of USD {limit}."
                self.notes.append(outcome.reason)
                return outcome
            agent = self._hire(
                f"a-op-{assignment}", spec, manager.agent_id, operator_id=spec.operator_id
            )
            if failed is not None:  # the manager reassigns the task to this operator
                self._escalate(failed[0], agent, failed[1], failed[2])
            task_v1 = TaskV1(
                task_id=assignment,
                run_id=self.run_id,
                role=task.role,
                instruction_ref=brief_ref(self.run_id, task_id),
                inputs=[slice_ref(self.run_id, item)],
                budget={
                    "max_input_tokens": self.policy.operator_max_input_tokens,
                    "max_output_tokens": self.policy.operator_max_output_tokens,
                    "max_usd": left,
                },
                deadline_s=self.policy.operator_deadline_s,
            )
            self.log.emit(
                "task_assigned",
                TaskAssignedPayload(
                    task=task_v1, agent_id=agent.agent_id, operator_id=spec.operator_id
                ),
            )
            self.citation_log.task_id = assignment
            self.slice_assignment.assign(assignment, item.source_id, slice_ref(self.run_id, item))
            try:
                record = await run_operator(
                    task_v1,
                    spec,
                    harness=self.harness,
                    store=self.store,
                    output_model=self.findings_model,
                    tools=self.tools,
                    base_prompt=self.operator_prompt,
                    skills_config=self.skills_config,
                    skills_dir=self.skills_dir,
                    budget_id=pool.id,
                    salvage=self._salvage_for(assignment),
                )
            finally:
                self.slice_assignment.clear()
            entries = self.caller.entries(assignment)
            spent += sum((e.usd_real for e in entries), ZERO_USD)
            self.caller.emit_attempts(agent.agent_id, record.attempts, entries)
            if record.stop_reason == "budget_exhausted":
                self._exhausted(agent, self._stop_of("operator", assignment, pool.id))
            self.log.emit(
                "task_result",
                TaskResultPayload(
                    agent_id=agent.agent_id, result=record.result, label=record.label
                ),
            )
            outcome.assignments.append(assignment)
            outcome.operator_ids.append(spec.operator_id)
            if record.label != "failed":
                outcome.status, outcome.reason = "ok", ""
                outcome.findings = Findings.model_validate(record.output)
                return outcome
            outcome.status = "failed"
            outcome.reason = (
                f"{assignment}: operator {spec.operator_id} failed ({record.stop_reason})"
            )
            if record.stop_reason in LEDGER_STOPS:
                self.notes.append(f"{outcome.reason}: it ran out of its budget.")
                return outcome
            ceiling = record.stop_reason in TASK_CEILING_STOPS
            if ceiling:
                outcome.reason += ": it hit its task ceiling"
            allowed = reassignments < self.policy.max_reassignments and not (
                ceiling and ceiling_reassignments
            )
            following = self._reassignment(spec, candidates, tried, ceiling) if allowed else None
            if following is not None:
                need = self._first_reservation_on(task_id, following)
                if limit - spent < need:
                    # The ledger would refuse its first call: do not hire it.
                    outcome.reason += (
                        f"; USD {limit - spent} is left of the task's limit, less than "
                        f"{following.operator_id}'s first call (USD {need})"
                    )
                    following = None
            note = outcome.reason + (
                "; the manager reassigns the task."
                if following is not None
                else "; escalated to the director."
            )
            self.notes.append(note)
            if following is None:
                self._escalate(manager, director, assignment, note)
            else:
                failed = (agent, assignment, note)
                reassignments += 1
                ceiling_reassignments += ceiling
            spec = following
        return outcome

    def _block_need(self, items: list[tuple[str, PlanTask, Slice]]) -> Decimal:
        """What a block needs so its operators can run one after another at their
        expected cost (the expected costs plus the headroom of the task in flight: its
        first reservation and, with `pool_covers_one_retry`, one retry's reservation, less
        its expected cost, for the task where that is largest), plus what its manager keeps
        (`_manager_keeps`)."""
        if not items:
            return ZERO_USD
        expected = sum((self.expected_cost[i[0]] for i in items), ZERO_USD)
        headroom = max(
            self.first_reservation[i[0]]
            + self.retry_reservation.get(i[0], ZERO_USD)
            - self.expected_cost[i[0]]
            for i in items
        )
        operators = expected + max(headroom, ZERO_USD)
        share = self.policy.manager_share
        by_share = operators * share / (1 - share) if share < 1 else operators
        return _floor(operators + max(by_share, self._manager_reservation()))

    def _manager_keeps(self, block_usd: Decimal) -> Decimal:
        """The manager's part of its block: `manager_share`, but at least one estimated
        consolidation reservation, so a small block's manager can still consolidate."""
        share = _floor(block_usd * self.policy.manager_share)
        return min(max(share, self._manager_reservation()), block_usd)

    def _manager_reservation(self) -> Decimal:
        """One consolidation call with a request of counts only, at the manager's model
        and output ceiling. Findings make the real request larger."""
        if self.manager_reservation is None:
            role = self.roles.manager
            tokens = self._manager_tokens(_consolidation_request("Block goal: x", [], 1, 1))
            self.manager_reservation = self.ledger.reservation_usd(
                role.model, tokens, role.max_output_tokens
            )
        return self.manager_reservation

    def _estimate(
        self, task: PlanTask, item: Slice, task_id: str = ""
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        """For the task's cheapest operator: its first reservation (its whole first request
        through the harness's calibrated estimate plus the role's output ceiling), its
        expected cost (the same input plus `expected_output_tokens_per_operator`), the
        same request's reservation one rung up the model ladder (zero at the top), and the
        reservation of one retry with its history (zero unless `pool_covers_one_retry`), at
        the ledger's prices. All zero when no operator serves the role."""
        specs = [s for s in self.catalog if s.role == task.role]
        if not specs:
            return ZERO_USD, ZERO_USD, ZERO_USD, ZERO_USD
        spec = min(specs, key=lambda s: (s.price_per_task_est_usd, -s.reputation, s.operator_id))
        if spec.role not in self.systems:
            composed = compose_system_prompt(
                spec.role,
                self.operator_prompt,
                config=self.skills_config,
                skills_dir=self.skills_dir,
            )
            self.systems[spec.role] = (
                f"{composed.text}\n\n{final_result_instructions(self.findings_model)}"
            )
        user = (
            f"Task t-0 ({spec.role}).\n\n{_brief(task, item)}\n\nInputs:\n\n"
            f"[{slice_ref(self.run_id, item)}]\n{item.text}"
        )
        config = self.harness.config
        protocol = config.model(spec.model).loop_protocol
        messages = prepare_messages(
            [
                {"role": "system", "content": self.systems[spec.role]},
                {"role": "user", "content": user},
            ],
            protocol,
            [],
        )
        json_object = (
            protocol == "json_protocol"
            and config.loop.json_protocol_response_format == "json_object"
        )
        built = build_request(
            ChatRequest(
                model=spec.model,
                messages=messages,
                run_id=self.run_id,
                level="operator",
                task_id="t-0",
                max_tokens=role_max_output_tokens(spec.role, self.skills_config),
                response_format=JsonObjectFormat() if json_object else None,
            ),
            config,
        )
        expected_output = min(self.policy.expected_output_tokens_per_operator, built.max_tokens)
        tokens = built.input_tokens_estimate
        if task_id:
            self.first_request[task_id] = (tokens, built.max_tokens)
        higher = config.escalation.next.get(spec.model)
        return (
            self.ledger.reservation_usd(spec.model, tokens, built.max_tokens),
            self.ledger.reservation_usd(spec.model, tokens, expected_output),
            self.ledger.reservation_usd(higher, tokens, built.max_tokens) if higher else ZERO_USD,
            self._retry_reservation(built) if self.policy.pool_covers_one_retry else ZERO_USD,
        )

    def _salvage_for(self, assignment: str) -> Callable[[str], Salvage | None]:
        """Salvage for one operator call: the complete part of a cut or broken reply,
        kept only when it validates against the operators' output model (on a probe that
        neither logs nor counts) and holds at least one claim. Accepted salvages are
        counted per task with the elements they dropped."""
        probe = SliceAssignment()
        model = payload_model(
            findings_model(
                self.evidence,
                None,
                probe,
                max_claims=self.policy.operator_max_claims,
                max_citations_per_claim=self.policy.operator_max_citations_per_claim,
            )
        )

        def accept(value: Any) -> bool:
            probe.assign(
                assignment, self.slice_assignment.source_id or "", self.slice_assignment.slice_ref
            )
            try:
                payload = model.model_validate(value)
            except ValidationError:
                return False
            return payload.status == "ok" and bool(payload.output.claims)

        def salvage(text: str) -> Salvage | None:
            found = salvage_json(text, accept)
            if found is not None:
                self.salvaged.setdefault(assignment, []).append(found.dropped_elements)
            return found

        return salvage

    def _retry_reservation(self, first: BuiltRequest) -> Decimal:
        """The reservation of one retry of `first`, at the ledger's prices."""
        retry = retry_request(first, self.policy, self.harness.config)
        return self.ledger.reservation_usd(
            retry.request.model, retry.input_tokens_estimate, retry.max_tokens
        )

    def _check_config(self, slicing: SlicingConfig) -> None:
        """Fail fast when a full slice plus the operator prompt could pass the operators'
        input token ceiling: such a task would stop on `token_ceiling` before its call."""
        limit = self.policy.operator_max_input_tokens
        for role in sorted({spec.role for spec in self.catalog}):
            overhead = self._operator_overhead(role)
            if slicing.max_slice_tokens + overhead > limit:
                raise ConfigError(
                    f"max_slice_tokens ({slicing.max_slice_tokens}, config/slicing.json) plus "
                    f"the {role} prompt overhead estimate ({overhead} tokens) is more than "
                    f"operator_max_input_tokens ({limit}, config/budget.json)"
                )

    def _operator_overhead(self, role: str) -> int:
        """The estimated input of an operator request without its slice: the system prompt,
        the protocol block, the task header and an instruction of up to 600 characters."""
        spec = min(
            (s for s in self.catalog if s.role == role),
            key=lambda s: (s.price_per_task_est_usd, -s.reputation, s.operator_id),
        )
        if role not in self.systems:
            composed = compose_system_prompt(
                role, self.operator_prompt, config=self.skills_config, skills_dir=self.skills_dir
            )
            self.systems[role] = (
                f"{composed.text}\n\n{final_result_instructions(self.findings_model)}"
            )
        user = (
            f"Task t-0000 ({role}).\n\n{'x' * 600}\n\nRead only the slice you are given: "
            "a source, lines 1000000-1000000 of 1000000.\n\nInputs:\n\n[store://run/slices/x]\n"
        )
        config = self.harness.config
        messages = prepare_messages(
            [{"role": "system", "content": self.systems[role]}, {"role": "user", "content": user}],
            config.model(spec.model).loop_protocol,
            [],
        )
        request = ChatRequest(
            model=spec.model,
            messages=messages,
            run_id=self.run_id,
            level="operator",
            task_id="t-0",
            max_tokens=role_max_output_tokens(role, self.skills_config),
        )
        return build_request(request, config).input_tokens_estimate

    def _first_reservation_on(self, task_id: str, spec: OperatorSpec) -> Decimal:
        """The reservation of the task's first request on `spec`'s model."""
        tokens, max_tokens = self.first_request.get(task_id, (0, 0))
        return self.ledger.reservation_usd(spec.model, tokens, max_tokens)

    def _reassignment(
        self,
        spec: OperatorSpec,
        candidates: list[OperatorSpec],
        tried: list[OperatorSpec],
        ceiling: bool,
    ) -> OperatorSpec | None:
        """Who gets a failed task next: the next catalog operator for the role; after a
        task ceiling with no catalog operator left, the same operator one rung up the
        model ladder."""
        following = next((c for c in candidates if c not in tried), None)
        if following is not None or not ceiling:
            return following
        higher = self.harness.config.escalation.next.get(spec.model)
        if higher is None:
            return None
        rung = spec.model_copy(update={"model": higher})
        return None if rung in tried else rung

    # -- helpers -------------------------------------------------------------------------

    def _hire(
        self,
        agent_id: str,
        role: RoleSpec | OperatorSpec,
        parent_id: str | None,
        *,
        operator_id: str | None = None,
    ) -> AgentNode:
        level: Level = role.level if isinstance(role, RoleSpec) else "operator"
        agent = AgentNode(
            agent_id=agent_id,
            level=level,
            role=role.role,
            model=role.model,
            operator_id=operator_id,
            parent_id=parent_id,
            skills=list(role.skills),
            tools=list(role.tools) if isinstance(role, OperatorSpec) else [],
            status="hired",
        )
        self.log.emit("agent_hired", AgentHiredPayload(agent=agent))
        return agent

    def _say(self, text: str) -> None:
        count = sum(1 for event in self.log.events if event.type == "message")
        message = ChatMessage(
            message_id=f"m-{count + 1}",
            run_id=self.run_id,
            sender="director",
            text=text,
            ts=self.log.now(),
        )
        self.log.emit("message", MessagePayload(message=message))

    def _allocate(
        self,
        agent: AgentNode,
        holder: AgentNode,
        budget_id: str,
        usd: Decimal,
        *,
        parent: str | None = None,
    ) -> Allocation:
        """Hold `usd` for `agent` out of `holder`'s budget: `parent`, or the run."""
        allocation = self.ledger.allocate(self.run_id, budget_id, usd, parent=parent)
        self._budget_event("allocated", agent, holder, allocation.usd, parent)
        return allocation

    def _close(self, allocation: Allocation, agent: AgentNode, holder: AgentNode) -> Decimal:
        released = self.ledger.close(allocation)
        self._budget_event("released", agent, holder, released, allocation.parent)
        return released

    def _budget_event(
        self,
        action: AllocationAction,
        agent: AgentNode,
        holder: AgentNode,
        usd: Decimal,
        parent: str | None,
    ) -> None:
        self.log.emit(
            "budget_allocation",
            BudgetAllocationPayload(
                action=action,
                agent_id=agent.agent_id,
                parent_agent_id=holder.agent_id,
                usd=usd,
                parent_free_usd=self.ledger.free(self.run_id, parent),
            ),
        )

    def _stop_of(self, level: Level, task_id: str, budget_id: str | None) -> CapReached | None:
        """The ledger stop that refused a call, in the order the ledger checks: the
        allocation and its parents, the run, the level, then the task."""
        report = self.ledger.report(self.run_id)
        parents = {node.id: node.parent for node in report.allocations}
        path: list[tuple[str, str]] = []
        while budget_id is not None:
            path.append(("budget", budget_id))
            budget_id = parents[budget_id]
        path += [("run", self.run_id), ("level", level), ("task", task_id)]
        stops = {(stop.scope, stop.key): stop for stop in report.stops}
        return next((stops[key] for key in path if key in stops), None)

    def _exhausted(self, agent: AgentNode, stop: CapReached | None) -> None:
        if stop is None:
            return
        self.log.emit(
            "budget_exhausted",
            BudgetExhaustedPayload(
                agent_id=agent.agent_id,
                level=agent.level,
                scope=stop.scope,
                key=stop.key,
                cap_usd=stop.cap_usd,
                committed_usd=stop.committed_usd,
                requested_usd=stop.requested_usd,
            ),
        )

    def _escalate(
        self, source: AgentNode, target: AgentNode, task_id: str | None, reason: str
    ) -> None:
        self.log.emit(
            "escalation",
            EscalationPayload(
                from_agent_id=source.agent_id,
                to_agent_id=target.agent_id,
                task_id=task_id,
                reason=reason,
            ),
        )

    def _fail_on_budget(
        self, director: AgentNode, stop: CapReached | None, message: str
    ) -> TeamRun:
        self._exhausted(director, stop)
        details: dict[str, Any] = {"level": director.level}
        if stop is not None:
            details |= {
                "scope": stop.scope,
                "key": stop.key,
                "cap_usd": format_usd(stop.cap_usd),
                "committed_usd": format_usd(stop.committed_usd),
                "requested_usd": format_usd(stop.requested_usd),
            }
        return self._fail("budget_exhausted", message, details)

    def _plan_format(self) -> JsonSchemaFormat | None:
        """The plan's schema as a wrapped json_schema response_format, inlined (no $ref),
        when the director's role turns it on; None (nothing sent) otherwise."""
        if self.roles.director.plan_response_format != "json_schema":
            return None
        schema = payload_model(self.plan_model).model_json_schema()
        return JsonSchemaFormat(name="PlanPayload", schema=inline_refs(schema), strict=True)

    def _stopped(self, plan: Plan) -> TeamRun:
        """The run ended on purpose after its plan: `cancelled` in the contract's terms,
        and partial, since no slice was read."""
        report = self.ledger.report(self.run_id)
        self.log.emit(
            "run_finished",
            RunFinishedPayload(
                status="cancelled",
                partial=True,
                spent_usd=report.spent_usd,
                predicted_usd=sum((e.usd_predicted for e in report.entries), ZERO_USD),
                package_url=None,
            ),
        )
        return TeamRun(
            run_id=self.run_id,
            status="cancelled",
            partial=True,
            plan=plan,
            blocks=[],
            audit=None,
            evidence=None,
            notes=self.notes,
            events=self.log.events,
            report=report,
            unread_slices=self._unread([]),
            empty_sources=list(self.slices.empty_sources),
        )

    def _fail(self, code: str, message: str, details: dict[str, Any]) -> TeamRun:
        report = self.ledger.report(self.run_id)
        self.log.emit(
            "run_failed",
            RunFailedPayload(
                error=ErrorBody(code=code, message=message, details=details),
                partial=False,
                spent_usd=report.spent_usd,
            ),
        )
        return TeamRun(
            run_id=self.run_id,
            status="failed",
            partial=False,
            plan=self.plan,
            blocks=[],
            audit=None,
            evidence=None,
            notes=self.notes,
            events=self.log.events,
            report=report,
            unread_slices=self._unread([]),
            empty_sources=list(self.slices.empty_sources),
        )

    def _unread(self, blocks: list[BlockOutcome]) -> list[UnreadRange]:
        """The line ranges of every source that no completed operator task read."""
        read: dict[str, list[Slice]] = {source_id: [] for source_id in self.slices_of}
        for block in blocks:
            for task in block.tasks:
                if task.status == "ok":
                    read[task.slice.source_id].append(task.slice)
        return [
            UnreadRange(source_id, first, last)
            for source_id, items in read.items()
            for first, last in coverage(items, self.slices.line_counts[source_id])
        ]

    def _plan_request(self, goal: str) -> str:
        roles = sorted({spec.role for spec in self.catalog})
        sources = []
        for source_id, items in self.slices_of.items():
            lines = self.slices.line_counts[source_id]
            if items:
                sources.append(f"- {source_id}: {lines} lines, {len(items)} slices")
            else:
                sources.append(f"- {source_id}: empty, nothing to read")
        return (
            f"Goal: {goal}\n\nOperator roles you can use: {', '.join(roles)}\n"
            "Sources (each task reads one source; every slice of it goes to its own "
            "operator):\n" + ("\n".join(sources) or "none") + "\n"
            f"Plan at most {self.policy.max_blocks} blocks, each with at most "
            f"{self.policy.max_tasks_per_block} tasks. Each task needs one of the operator "
            "roles, the source_id it reads and an instruction that stands on its own. Every "
            "source that is not empty must be read by at least one task."
        )

    def _batches(self, header: str, entries: list[str]) -> list[list[str]]:
        """The findings in batches whose manager request stays under
        `manager_max_input_tokens` (estimated). One batch when everything fits; a finding
        larger than the limit on its own still gets a batch of its own."""
        limit = self.policy.manager_max_input_tokens
        batches: list[list[str]] = [[]]
        for entry in entries:
            trial = [*batches[-1], entry]
            fits = self._manager_tokens(_consolidation_request(header, trial, 2, 2)) <= limit
            if batches[-1] and not fits:
                batches.append([entry])
            else:
                batches[-1] = trial
        return batches

    def _manager_tokens(self, user: str) -> int:
        """The estimated input of a manager call with `user` as its request."""
        role = self.roles.manager
        if "manager" not in self.systems:
            composed = compose_system_prompt(
                role.role, MANAGER_PROMPT, config=self.skills_config, skills_dir=self.skills_dir
            )
            self.systems["manager"] = (
                f"{composed.text}\n\n{final_result_instructions(BlockSummary)}"
            )
        config = self.harness.config
        messages = prepare_messages(
            [
                {"role": "system", "content": self.systems["manager"]},
                {"role": "user", "content": user},
            ],
            config.model(role.model).loop_protocol,
            [],
        )
        request = ChatRequest(
            model=role.model,
            messages=messages,
            run_id=self.run_id,
            level="manager",
            task_id="estimate",
            max_tokens=role.max_output_tokens,
        )
        return build_request(request, config).input_tokens_estimate

    def _closing_message(self, blocks: list[BlockOutcome], outcome: Any) -> str:
        verdict: AuditVerdict = outcome.verdict
        tasks = [t for b in blocks for t in b.tasks]
        done = sum(t.status == "ok" for t in tasks)
        text = f"Done: {done} of {len(tasks)} tasks completed."
        if outcome.status == "inconclusive":
            text += f" Diagnosis: inconclusive ({outcome.reason})."
        else:
            counts = outcome.counts
            text += (
                f" Diagnosis: {counts.supported} claims supported, {counts.withdrawn} withdrawn."
            )
        if outcome.withdrawn:
            text += (
                " Withdrawn: "
                + ", ".join(f"{w.claim.claim_id} ({w.reason})" for w in outcome.withdrawn)
                + "."
            )
        text += f" Audit: {verdict.verdict}."
        unread = self._unread(blocks)
        if unread:
            ranges = ", ".join(f"{u.source_id} {u.line_start}-{u.line_end}" for u in unread)
            text += f" Unread lines: {ranges}."
        if verdict.warning:
            text += f" {verdict.warning}"
        if self.notes:
            text += " Notes: " + " ".join(self.notes)
        return text
