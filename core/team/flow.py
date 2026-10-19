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
2. It hires the auditor and allocates its share, then hires one manager per block and
   splits what is free equally into one allocation each (`BudgetPolicy`).
3. A manager keeps its own share free and gives each task an operator allocation; the
   operator's calls are drawn from it, and the task's USD cap is the same amount. When
   the operator is done its allocation is closed, so the unspent part goes back to the
   manager. How a failed task goes on depends on why it stopped:
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
4. The manager makes one consolidation call inside its allocation, then closes it; the
   unspent part goes back to the run.
5. The director writes the diagnosis (`Diagnosis`, validated by `diagnosis_model`, so its
   citations pass the same check as the operators'), drawn from the run. It receives the
   context sources in full (`context_sources`, for example the ticket and the runbook),
   the source inventory, and the managers' summaries and the operators' findings under
   their store references, and it may cite evidence lines directly.
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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Literal

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
from rookwise.evidence import EvidenceBundle, EvidenceReport, verify
from rookwise.harness import Harness, Tool
from rookwise.ledger import Allocation, CapReached, RunReport
from rookwise.money import ZERO_USD, format_usd, to_micro_usd
from rookwise.runner import DEFAULT_BASE_PROMPT, OperatorSpec, run_operator
from rookwise.schemas import Level, TaskV1
from rookwise.skills.loader import SKILLS_DIR
from rookwise.slicing import Slice, SlicingConfig, coverage, load_slicing_config, slice_bundle
from rookwise.store import Store
from rookwise.team.agents import AgentCaller
from rookwise.team.auditor import (
    ClaimCounts,
    DiagnosisStatus,
    WithdrawnClaim,
    audit,
    render_source,
)
from rookwise.team.config import BudgetPolicy, RoleSpec, load_team_roles
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
    diagnosis_model,
    findings_model,
    plan_model,
)

DIRECTOR_PROMPT = (
    "You are the director of a team of AI agents. Split the goal into blocks of work, one "
    "per manager, and each block into tasks for operators. Each task names an operator role "
    "and the one source it reads, and every source must be read by at least one task. Use "
    "only the operator roles and source ids you are given. Keep to the required final "
    "result format."
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
    'line_end. Never join lines in one quote, with a line break, " | " or anything else.'
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


@dataclass(frozen=True)
class UnreadRange:
    """Lines of a source that no completed operator task read."""

    source_id: str
    line_start: int
    line_end: int


@dataclass
class TeamRun:
    run_id: str
    status: Literal["finished", "failed"]
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
) -> TeamRun:
    """Run the hierarchy for one goal. The run must already be open in the harness's
    ledger (the administrator layer opens it with the run cap). `slicing` defaults to
    config/slicing.json. `context_sources` are the source ids the director reads in full
    for its diagnosis (for example the ticket and the runbook)."""
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
        policy=policy or BudgetPolicy(),
        tools=tools or {},
        log=EventLog(run_id, mode=mode, clock=clock),
        simulated_case=simulated_case,
        slicing=slicing or load_slicing_config(),
        context_sources=tuple(context_sources),
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
    ) -> None:
        self.run_id = run_id
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
        self.findings_model = findings_model(evidence, self.citation_log)
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
        # Every agent is hired before its allocation, so its budget_allocation event can
        # name it. The amounts fit what is free, so no allocation here is refused.
        auditor = self._hire("a-auditor", self.roles.auditor, None)
        auditor_share = _floor(self.ledger.free(self.run_id) * self.policy.auditor_share)
        auditor_budget = self._allocate(auditor, director, "budget:auditor", auditor_share)
        per_block = _floor(self.ledger.free(self.run_id) / len(plan.blocks))
        managers: list[tuple[AgentNode, Allocation]] = []
        for index in range(1, len(plan.blocks) + 1):
            manager = self._hire(f"a-manager-b-{index}", self.roles.manager, director.agent_id)
            budget = self._allocate(manager, director, f"budget:b-{index}", per_block)
            managers.append((manager, budget))
        blocks: list[BlockOutcome] = []
        number = 0
        for index, block in enumerate(plan.blocks, 1):
            manager, budget = managers[index - 1]
            items: list[tuple[str, PlanTask, Slice]] = []
            for task in block.tasks:
                for item in self.slices_of[task.source_id]:
                    number += 1
                    items.append((f"t-{number}", task, item))
            blocks.append(await self._manage(f"b-{index}", block, budget, items, manager, director))

        diagnosis, missing = await self._diagnose(goal, director, blocks)

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
        findings = ["Managers' consolidated findings, by reference:"]
        for block in blocks:
            findings.append(
                f"[{summary_ref(self.run_id, block.block_id)}]\nBlock {block.block_id}: "
                f"{block.goal}\nSummary: {block.summary or '(none)'}"
            )
            for task in block.tasks:
                if task.findings is None:
                    findings.append(
                        f"- {task.task_id} ({task.role}, {task.slice.slice_id}): not done. "
                        f"{task.reason}"
                    )
                    continue
                ref = f"store://{self.run_id}/results/{task.assignments[-1]}"
                findings.append(
                    f"[{ref}] {task.task_id} ({task.role}, {task.slice.slice_id}):\n"
                    + task.findings.model_dump_json()
                )
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
        own = _floor(budget.usd * self.policy.manager_share)
        per_task = _floor((budget.usd - own) / len(items)) if items else ZERO_USD
        outcomes = [
            await self._staff(task_id, task, item, manager, director, budget, own, per_task)
            for task_id, task, item in items
        ]
        done = [t for t in outcomes if t.status == "ok"]
        summary, reason = None, ""
        summary_id = f"{block_id}-summary"
        if not done:
            reason = f"Block {block_id} has no completed task; escalated to the director."
            self._escalate(manager, director, None, reason)
        else:
            result = await self.caller.call(
                manager,
                self.roles.manager,
                level="manager",
                task_id=summary_id,
                base_prompt=MANAGER_PROMPT,
                user=self._consolidation_request(block, outcomes),
                output_model=BlockSummary,
                budget_id=budget.id,
            )
            if result.ok and result.validation is not None:
                summary = result.validation.payload.output.summary  # type: ignore[attr-defined]
                self.store.put(summary_ref(self.run_id, block_id), summary)
            elif result.stop_reason == "budget_exhausted":
                reason = f"Manager {block_id} ran out of budget before its consolidation call."
                self._exhausted(manager, self._stop_of("manager", summary_id, budget.id))
            else:
                reason = (
                    f"Manager {block_id} could not consolidate ({result.stop_reason}); "
                    "escalated to the director."
                )
                self._escalate(manager, director, summary_id, reason)
        if reason:
            self.notes.append(reason)
        released = self._close(budget, manager, director)
        if not done:
            status: BlockStatus = "failed"
        elif len(done) == len(outcomes) and summary is not None:
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
        )

    async def _staff(
        self,
        task_id: str,
        task: PlanTask,
        item: Slice,
        manager: AgentNode,
        director: AgentNode,
        budget: Allocation,
        own: Decimal,
        per_task: Decimal,
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
        brief = (
            f"{task.instruction}\n\nRead only the slice you are given: {item.source_id}, "
            f"lines {item.line_start}-{item.line_end} of {item.line_count}."
        )
        self.store.put(brief_ref(self.run_id, task_id), brief)
        spec: OperatorSpec | None = candidates[0]
        tried: list[OperatorSpec] = []
        reassignments, ceiling_reassignments = 0, 0
        number = 0
        while spec is not None:
            number += 1
            tried.append(spec)
            assignment = task_id if number == 1 else f"{task_id}.{number}"
            amount = min(per_task, max(self.ledger.free(self.run_id, budget.id) - own, ZERO_USD))
            if amount <= 0:
                outcome.reason = f"{task_id}: manager {manager.agent_id} has no budget left for it."
                self.notes.append(outcome.reason)
                return outcome
            agent = self._hire(
                f"a-op-{assignment}", spec, manager.agent_id, operator_id=spec.operator_id
            )
            if failed is not None:  # the manager reassigns the task to this operator
                self._escalate(failed[0], agent, failed[1], failed[2])
            operator_budget = self._allocate(
                agent, manager, f"budget:{assignment}", amount, parent=budget.id
            )
            task_v1 = TaskV1(
                task_id=assignment,
                run_id=self.run_id,
                role=task.role,
                instruction_ref=brief_ref(self.run_id, task_id),
                inputs=[slice_ref(self.run_id, item)],
                budget={
                    "max_input_tokens": self.policy.operator_max_input_tokens,
                    "max_output_tokens": self.policy.operator_max_output_tokens,
                    "max_usd": amount,
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
            record = await run_operator(
                task_v1,
                spec,
                harness=self.harness,
                store=self.store,
                output_model=self.findings_model,
                tools=self.tools,
                base_prompt=OPERATOR_PROMPT,
                skills_config=self.skills_config,
                skills_dir=self.skills_dir,
                budget_id=operator_budget.id,
            )
            self.caller.emit_attempts(
                agent.agent_id, record.attempts, self.caller.entries(assignment)
            )
            if record.stop_reason == "budget_exhausted":
                self._exhausted(agent, self._stop_of("operator", assignment, operator_budget.id))
            self.log.emit(
                "task_result",
                TaskResultPayload(
                    agent_id=agent.agent_id, result=record.result, label=record.label
                ),
            )
            self._close(operator_budget, agent, manager)
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

    @staticmethod
    def _consolidation_request(block: PlanBlock, outcomes: list[TaskOutcome]) -> str:
        lines = [f"Block goal: {block.goal}", "", "Operator results:"]
        for outcome in outcomes:
            if outcome.findings is not None:
                claims = len(outcome.findings.claims)
                lines.append(
                    f"- {outcome.task_id} ({outcome.role}, {outcome.slice.slice_id}): "
                    f"{outcome.findings.summary} [{claims} claims]"
                )
            else:
                lines.append(
                    f"- {outcome.task_id} ({outcome.role}, {outcome.slice.slice_id}): not done. "
                    f"{outcome.reason}"
                )
        return "\n".join(lines)

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
