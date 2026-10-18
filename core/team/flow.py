"""The team hierarchy: director -> managers -> operators -> auditor.

Built only on the harness and the runner. Every model call goes through
`rookwise.harness`: the director, managers and auditor through `run_with_escalation`
with no tools (`rookwise.team.agents`), operators through `rookwise.runner.run_operator`.
The ledger, rate limits, retries, repairs and the escalation ladder therefore apply to
every call. Roles, models and skills are data (`rookwise.team.config`); the tasks come
from the director's plan, so nothing here depends on a domain.

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
5. The auditor gets the deliverable and the evidence bundle (`rookwise.team.auditor`).

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
from rookwise.evidence import Claim, EvidenceBundle, EvidenceReport
from rookwise.harness import Harness, Tool
from rookwise.ledger import Allocation, CapReached, RunReport
from rookwise.money import ZERO_USD, format_usd, to_micro_usd
from rookwise.runner import DEFAULT_BASE_PROMPT, OperatorSpec, run_operator
from rookwise.schemas import Level, TaskV1
from rookwise.skills.loader import SKILLS_DIR
from rookwise.store import Store
from rookwise.team.agents import AgentCaller
from rookwise.team.auditor import audit, render_source
from rookwise.team.config import BudgetPolicy, RoleSpec, load_team_roles
from rookwise.team.events import EventLog
from rookwise.team.models import BlockSummary, Findings, Plan, PlanBlock, PlanTask

DIRECTOR_PROMPT = (
    "You are the director of a team of AI agents. Split the goal into blocks of work, one "
    "per manager, and each block into tasks for operators. Use only the operator roles you "
    "are given. Keep to the required final result format."
)
MANAGER_PROMPT = (
    "You are a manager in a team of AI agents. Consolidate your operators' results into one "
    "short summary of your block. Keep to the required final result format."
)
OPERATOR_PROMPT = (
    f"{DEFAULT_BASE_PROMPT} Back every claim with citations: the source id, the first and "
    "last line numbers, and a quote copied exactly from those lines."
)
# Why an operator stopped. A task ceiling is this one task hitting its own cap (its
# output ceiling or its token budget); a ledger stop is the ledger refusing a reservation.
TASK_CEILING_STOPS = ("length", "token_ceiling")
LEDGER_STOPS = ("budget_exhausted",)

TaskStatus = Literal["ok", "failed", "not_run"]
BlockStatus = Literal["ok", "partial", "failed"]


@dataclass
class TaskOutcome:
    """One task of the plan. `assignments` holds the task_v1 ids, one per operator tried."""

    task_id: str
    role: str
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
) -> TeamRun:
    """Run the hierarchy for one goal. The run must already be open in the harness's
    ledger (the administrator layer opens it with the run cap)."""
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
        for source_id, text in self.evidence.sources.items():
            self.store.put(source_ref(self.run_id, source_id), render_source(source_id, text))

        result = await self.caller.call(
            director,
            self.roles.director,
            level="director",
            task_id="plan",
            base_prompt=DIRECTOR_PROMPT,
            user=self._plan_request(goal),
            output_model=Plan,
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
        self._say(f"{plan.summary} ({len(plan.blocks)} blocks, {tasks} tasks.)")

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
        first = 1
        for index, block in enumerate(plan.blocks, 1):
            manager, budget = managers[index - 1]
            ids = [f"t-{first + k}" for k in range(len(block.tasks))]
            first += len(block.tasks)
            blocks.append(await self._manage(f"b-{index}", block, budget, ids, manager, director))

        claims = [
            Claim(claim_id=f"{t.task_id}:{c.claim_id}", text=c.text, citations=c.citations)
            for b in blocks
            for t in b.tasks
            if t.findings is not None
            for c in t.findings.claims
        ]
        outcome = await audit(
            self.caller,
            auditor,
            self.roles.auditor,
            goal=goal,
            deliverable=self._deliverable(blocks),
            claims=claims,
            bundle=self.evidence,
            budget_id=auditor_budget.id,
        )
        if outcome.budget_exhausted:
            self._exhausted(auditor, self._stop_of("auditor", "audit", auditor_budget.id))
            self.notes.append("The auditor ran out of budget: only the deterministic check ran.")
        self.log.emit("audit_result", AuditResultPayload(audit=outcome.verdict))
        self._close(auditor_budget, auditor, director)
        partial = outcome.budget_exhausted or any(b.status != "ok" for b in blocks)
        self._say(self._closing_message(blocks, outcome.verdict))
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
        )

    # -- manager -------------------------------------------------------------------------

    async def _manage(
        self,
        block_id: str,
        block: PlanBlock,
        budget: Allocation,
        task_ids: list[str],
        manager: AgentNode,
        director: AgentNode,
    ) -> BlockOutcome:
        own = _floor(budget.usd * self.policy.manager_share)
        per_task = _floor((budget.usd - own) / len(block.tasks))
        outcomes = [
            await self._staff(task_id, task, manager, director, budget, own, per_task)
            for task_id, task in zip(task_ids, block.tasks, strict=True)
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
        manager: AgentNode,
        director: AgentNode,
        budget: Allocation,
        own: Decimal,
        per_task: Decimal,
    ) -> TaskOutcome:
        outcome = TaskOutcome(task_id=task_id, role=task.role)
        failed: tuple[AgentNode, str, str] | None = None  # operator, task_v1 id, reason
        candidates = sorted(
            (spec for spec in self.catalog if spec.role == task.role),
            key=lambda spec: (spec.price_per_task_est_usd, -spec.reputation, spec.operator_id),
        )
        if not candidates:
            outcome.reason = f"{task_id}: no operator in the catalog for role {task.role}."
            self.notes.append(outcome.reason)
            return outcome
        self.store.put(brief_ref(self.run_id, task_id), task.instruction)
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
                inputs=[source_ref(self.run_id, s) for s in self.evidence.sources],
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
            record = await run_operator(
                task_v1,
                spec,
                harness=self.harness,
                store=self.store,
                output_model=Findings,
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
        )

    def _plan_request(self, goal: str) -> str:
        roles = sorted({spec.role for spec in self.catalog})
        sources = ", ".join(self.evidence.sources) or "none"
        return (
            f"Goal: {goal}\n\nOperator roles you can use: {', '.join(roles)}\n"
            f"Sources the operators can cite: {sources}\n"
            f"Plan at most {self.policy.max_blocks} blocks, each with at most "
            f"{self.policy.max_tasks_per_block} tasks. Each task needs one of the operator "
            "roles and an instruction that stands on its own."
        )

    @staticmethod
    def _consolidation_request(block: PlanBlock, outcomes: list[TaskOutcome]) -> str:
        lines = [f"Block goal: {block.goal}", "", "Operator results:"]
        for outcome in outcomes:
            if outcome.findings is not None:
                claims = len(outcome.findings.claims)
                lines.append(
                    f"- {outcome.task_id} ({outcome.role}): {outcome.findings.summary} "
                    f"[{claims} claims]"
                )
            else:
                lines.append(f"- {outcome.task_id} ({outcome.role}): not done. {outcome.reason}")
        return "\n".join(lines)

    @staticmethod
    def _deliverable(blocks: list[BlockOutcome]) -> str:
        parts = []
        for block in blocks:
            parts.append(f"Block {block.block_id}: {block.goal}")
            parts.append(f"Manager summary: {block.summary or '(none)'}")
            for task in block.tasks:
                text = (
                    task.findings.summary
                    if task.findings is not None
                    else f"not done. {task.reason}"
                )
                parts.append(f"- {task.task_id} ({task.role}): {text}")
        return "\n".join(parts)

    def _closing_message(self, blocks: list[BlockOutcome], verdict: AuditVerdict) -> str:
        tasks = [t for b in blocks for t in b.tasks]
        done = sum(t.status == "ok" for t in tasks)
        text = f"Done: {done} of {len(tasks)} tasks completed. Audit: {verdict.verdict}."
        if verdict.warning:
            text += f" {verdict.warning}"
        if self.notes:
            text += " Notes: " + " ".join(self.notes)
        return text
