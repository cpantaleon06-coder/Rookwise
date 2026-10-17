"""Generate the SYNTHETIC API v1 fixtures in examples/api/ (docs/api.md, docs/api-mock.md).

Nothing here is model output. The run, its texts and its numbers are written by this
script and labelled "[synthetic]". Costs go through the real `InMemoryLedger` with the
prices in config/prices.json, so every sum in the fixtures adds up exactly. Money is
Decimal here and a six-decimal string in the files (docs/api.md, "Conventions").

Files:
- examples/api/recorded_run.json: one complete recorded run as a static bundle (modes,
  run, run list, org chart, ledger, messages, tasks, delivery package).
- examples/api/recorded_run.events.json: the same run as an SSE replay: every event with
  the delay before it, covering a hire, a tool call, a repair (retry), an escalation up
  the model ladder, sub-budgets allocated and released, a reassignment by the manager, an
  operator stopped on its budget, an audit pass and budget updates.
- examples/api/live_refused.json: a refused live run (HTTP 429 and its error body, the
  modes view at that moment) and the stream of a live run refused after creation.

Usage:
    python scripts/gen_api_fixtures.py           # write the files
    python scripts/gen_api_fixtures.py --check   # exit 1 if any file differs
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # noqa: E402 (lets `rookwise` resolve from a checkout)

from rookwise.api import models as api  # noqa: E402
from rookwise.harness.escalate import AttemptRecord  # noqa: E402
from rookwise.ledger import Allocation, CapReached, Caps, InMemoryLedger, Usage  # noqa: E402
from rookwise.money import ZERO_USD  # noqa: E402
from rookwise.schemas import ResultV1, TaskV1  # noqa: E402

OUT_DIR = REPO_ROOT / "examples" / "api"
RUN_ID = "run_8f2c1a7d4b"
RECORDING_ID = "rec-demo-bakery-001"
GOAL = "[synthetic] Plan a one-page website for a simulated corner bakery."
BUDGET_USD = Decimal("0.25")
AUDITOR_USD, MANAGER_USD, TASK_USD = Decimal("0.010"), Decimal("0.015"), Decimal("0.003")
START = datetime(2026, 10, 20, 15, 0, 0, tzinfo=UTC)
ULTRA, SUPER, LIGHTNING = "nemotron-3-ultra", "nemotron-3-super", "nemotron-3.5-lightning"
FIXTURE_NOTE = {
    "synthetic": True,
    "api_version": "v1",
    "note": (
        "SYNTHETIC FIXTURE written by scripts/gen_api_fixtures.py. It is not real model "
        "output and not a measured run; texts are marked [synthetic] and numbers are "
        "arithmetic on config/prices.json. The demo case itself is simulated."
    ),
}


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json")


class Timeline:
    """Builds events with seq, ids and timestamps, and keeps the ledger."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.clock = START
        self.ledger = InMemoryLedger()
        self.ledger.open_run(RUN_ID, Caps(run_usd=BUDGET_USD))

    def emit(self, delay_ms: int, event_type: str, payload: dict[str, Any]) -> Any:
        self.clock += timedelta(milliseconds=delay_ms)
        seq = len(self.events) + 1
        event = api.SSE_EVENT_ADAPTER.validate_python(
            {
                "id": f"{RUN_ID}:{seq}",
                "seq": seq,
                "run_id": RUN_ID,
                "mode": "recorded",
                "ts": self.clock,
                "type": event_type,
                "payload": payload,
            }
        )
        self.events.append({"delay_ms": delay_ms, "event": _dump(event)})
        return event

    def charge(
        self,
        level,
        task_id,
        model,
        input_tokens,
        output_tokens,
        predicted,
        skills=(),
        estimated=False,
        budget_id=None,
    ):
        reservation = self.ledger.reserve(
            RUN_ID,
            level=level,
            task_id=task_id,
            model=model,
            input_tokens=input_tokens,
            max_output_tokens=output_tokens,
            usd_predicted=predicted,
            skills=skills,
            budget_id=budget_id,
        )
        return self.ledger.charge(
            reservation,
            Usage(input_tokens, output_tokens),
            ts=self.clock,
            usage_estimated=estimated,
        )

    def refuse(self, level, task_id, model, input_tokens, max_output_tokens, budget_id):
        """A reservation the ledger refuses: the CapReached it raises."""
        try:
            self.ledger.reserve(
                RUN_ID,
                level=level,
                task_id=task_id,
                model=model,
                input_tokens=input_tokens,
                max_output_tokens=max_output_tokens,
                usd_predicted=ZERO_USD,
                budget_id=budget_id,
            )
        except CapReached as stop:
            return stop
        raise AssertionError(f"the reservation for {task_id} fits its budget")

    def allocate(self, delay_ms, agent_id, parent_agent_id, budget_id, usd, parent=None):
        allocation = self.ledger.allocate(RUN_ID, budget_id, usd, parent=parent)
        self._allocation(delay_ms, "allocated", agent_id, parent_agent_id, allocation.usd, parent)
        return allocation

    def release(self, delay_ms, allocation: Allocation, agent_id, parent_agent_id) -> None:
        released = self.ledger.close(allocation)
        self._allocation(
            delay_ms, "released", agent_id, parent_agent_id, released, allocation.parent
        )

    def _allocation(self, delay_ms, action, agent_id, parent_agent_id, usd, parent) -> None:
        self.emit(
            delay_ms,
            "budget_allocation",
            {
                "action": action,
                "agent_id": agent_id,
                "parent_agent_id": parent_agent_id,
                "usd": usd,
                "parent_free_usd": self.ledger.free(RUN_ID, parent),
            },
        )

    def budget(self, delay_ms: int, entry) -> None:
        report = self.ledger.report(RUN_ID)
        self.emit(
            delay_ms,
            "budget_update",
            {
                "spent_usd": report.spent_usd,
                "held_usd": report.held_usd,
                "predicted_usd": sum((e.usd_predicted for e in report.entries), ZERO_USD),
                "cap_usd": BUDGET_USD,
                "spent_by_level": dict(report.spent_by_level),
                "entry": _dump(entry),
            },
        )


def _agent(
    agent_id, level, role, model, parent, status="hired", operator_id=None, skills=(), tools=()
):
    return api.AgentNode(
        agent_id=agent_id,
        level=level,
        role=role,
        model=model,
        operator_id=operator_id,
        parent_id=parent,
        skills=list(skills),
        tools=list(tools),
        status=status,
    )


def _task(task_id, role, inputs, max_usd) -> TaskV1:
    return TaskV1(
        task_id=task_id,
        run_id=RUN_ID,
        role=role,
        instruction_ref=f"store://{RUN_ID}/briefs/{task_id}",
        inputs=inputs,
        budget={"max_input_tokens": 20_000, "max_output_tokens": 4_000, "max_usd": max_usd},
        deadline_s=120,
    )


def _attempt(
    task_id,
    index,
    model,
    protocol,
    reason,
    retry_reason,
    status,
    ok,
    entries,
    errors=(),
    tools=None,
    steps=1,
    detail="",
):
    return AttemptRecord(
        task_id=task_id,
        attempt_index=index,
        model=model,
        protocol=protocol,
        reason=reason,
        retry_reason=retry_reason,
        loop_status=status,
        ok=ok,
        validation_errors=list(errors),
        length_retries=0,
        steps=steps,
        model_calls=len(entries),
        tool_calls=tools or {},
        usd=sum((e.usd_real for e in entries), ZERO_USD),
        input_tokens=sum(e.input_tokens for e in entries),
        output_tokens=sum(e.output_tokens for e in entries),
        usage_estimated=any(e.usage_estimated for e in entries),
        detail=detail,
    )


def _result(
    task: TaskV1, entries, notes: str, status: str = "ok", schema_valid: bool = True
) -> ResultV1:
    return ResultV1(
        task_id=task.task_id,
        status=status,
        output_ref=f"store://{RUN_ID}/results/{task.task_id}",
        usage={
            "input_tokens": sum(e.input_tokens for e in entries),
            "output_tokens": sum(e.output_tokens for e in entries),
            "usd": sum((e.usd_real for e in entries), ZERO_USD),
        },
        self_check={"schema_valid": schema_valid, "notes": notes},
    )


def recorded_run() -> tuple[dict[str, Any], dict[str, Any]]:
    t = Timeline()
    messages: list[api.ChatMessage] = []

    def say(delay, sender, text):
        message = api.ChatMessage(
            message_id=f"m-{len(messages) + 1}",
            run_id=RUN_ID,
            sender=sender,
            text=text,
            ts=t.clock + timedelta(milliseconds=delay),
        )
        messages.append(message)
        t.emit(delay, "message", {"message": _dump(message)})

    t.emit(
        0,
        "run_started",
        {
            "goal": GOAL,
            "mode": "recorded",
            "recording_id": RECORDING_ID,
            "budget_usd": BUDGET_USD,
            "board": False,
            "simulated_case": True,
        },
    )
    t.emit(
        50,
        "mode_notice",
        {
            "notice": "recorded_mode",
            "mode": "recorded",
            "detail": "Replaying a saved synthetic run. It costs nothing.",
        },
    )
    director = _agent("a-director", "director", "director", ULTRA, None)
    t.emit(300, "agent_hired", {"agent": _dump(director)})
    plan = t.charge("director", "plan", ULTRA, 3_000, 600, Decimal("0.0050"))
    t.budget(1_800, plan)
    say(
        100,
        "director",
        "[synthetic] Plan: one manager with a research task and two copywriting tasks "
        "(page copy and menu), within the USD 0.25 cap. Approve?",
    )
    say(2_000, "user", "[synthetic] Approved.")

    # The director holds the run budget: the auditor's allocation first, then the manager's.
    auditor = _agent("a-auditor", "auditor", "auditor", ULTRA, None, skills=["prose-style"])
    t.emit(200, "agent_hired", {"agent": _dump(auditor)})
    auditor_budget = t.allocate(50, "a-auditor", "a-director", "budget:auditor", AUDITOR_USD)
    manager = _agent("a-manager-1", "manager", "manager", SUPER, "a-director")
    t.emit(200, "agent_hired", {"agent": _dump(manager)})
    manager_budget = t.allocate(50, "a-manager-1", "a-director", "budget:b-1", MANAGER_USD)
    split = t.charge(
        "manager", "manage-1", SUPER, 2_000, 400, Decimal("0.0010"), budget_id=manager_budget.id
    )
    t.budget(1_200, split)

    def operator_budget(agent_id, task_id):
        return t.allocate(
            50, agent_id, "a-manager-1", f"budget:{task_id}", TASK_USD, parent=manager_budget.id
        )

    # t-1: research with one tool call, first pass ok.
    researcher = _agent(
        "a-op-research",
        "operator",
        "researcher",
        LIGHTNING,
        "a-manager-1",
        operator_id="researcher-lightning-01",
        skills=["prose-style"],
        tools=["tavily_search"],
    )
    t.emit(200, "agent_hired", {"agent": _dump(researcher)})
    budget1 = operator_budget("a-op-research", "t-1")
    task1 = _task("t-1", "researcher", [], TASK_USD)
    t.emit(
        100,
        "task_assigned",
        {
            "task": _dump(task1),
            "agent_id": "a-op-research",
            "operator_id": "researcher-lightning-01",
        },
    )
    t.emit(
        100,
        "task_started",
        {"task_id": "t-1", "agent_id": "a-op-research", "model": LIGHTNING, "attempt_index": 0},
    )
    call = t.charge(
        "operator",
        "t-1",
        LIGHTNING,
        900,
        40,
        Decimal("0.0001"),
        skills=["prose-style"],
        budget_id=budget1.id,
    )
    t.emit(
        700,
        "tool_called",
        {
            "task_id": "t-1",
            "agent_id": "a-op-research",
            "tool": "search",
            "ok": True,
            "run_tool_count": 1,
        },
    )
    final = t.charge(
        "operator",
        "t-1",
        LIGHTNING,
        1_100,
        180,
        Decimal("0.0001"),
        skills=["prose-style"],
        budget_id=budget1.id,
    )
    attempt1 = _attempt(
        "t-1",
        0,
        LIGHTNING,
        "native_tools",
        "first",
        None,
        "final",
        True,
        [call, final],
        tools={"search": 1},
        steps=2,
    )
    t.emit(900, "attempt_recorded", {"agent_id": "a-op-research", "attempt": _dump(attempt1)})
    t.budget(50, final)
    result1 = _result(task1, [call, final], "first_pass_ok")
    t.emit(
        50,
        "task_result",
        {"agent_id": "a-op-research", "result": _dump(result1), "label": "first_pass_ok"},
    )
    t.release(50, budget1, "a-op-research", "a-manager-1")

    # t-2: copywriting, two repairs, an interrupted stream, then escalation to Super.
    copywriter = _agent(
        "a-op-copy",
        "operator",
        "copywriter",
        LIGHTNING,
        "a-manager-1",
        operator_id="copywriter-lightning-01",
        skills=["prose-style"],
    )
    t.emit(200, "agent_hired", {"agent": _dump(copywriter)})
    budget2 = operator_budget("a-op-copy", "t-2")
    task2 = _task("t-2", "copywriter", [f"store://{RUN_ID}/results/t-1"], TASK_USD)
    t.emit(
        100,
        "task_assigned",
        {"task": _dump(task2), "agent_id": "a-op-copy", "operator_id": "copywriter-lightning-01"},
    )
    attempts2 = []
    plan2 = [
        (
            LIGHTNING,
            "first",
            None,
            "final",
            False,
            1_000,
            300,
            False,
            ["output.headline: Field required"],
            "",
        ),
        (
            LIGHTNING,
            "repair",
            "validation_failed",
            "final",
            False,
            1_300,
            300,
            False,
            ["output.body: String should have at most 600 characters"],
            "",
        ),
        (
            LIGHTNING,
            "repair",
            "validation_failed",
            "interrupted",
            False,
            1_600,
            1_024,
            True,
            ["(loop): ended with interrupted: ReadError: connection reset"],
            "ReadError: connection reset",
        ),
        (SUPER, "escalation", "interrupted", "final", True, 1_000, 350, False, [], ""),
    ]
    entries2 = []
    for index, (model, reason, retry, status, ok, tin, tout, est, errors, detail) in enumerate(
        plan2
    ):
        t.emit(
            150,
            "task_started",
            {"task_id": "t-2", "agent_id": "a-op-copy", "model": model, "attempt_index": index},
        )
        entry = t.charge(
            "operator",
            "t-2",
            model,
            tin,
            tout,
            Decimal("0.0002"),
            skills=["prose-style"],
            estimated=est,
            budget_id=budget2.id,
        )
        entries2.append(entry)
        protocol = "native_tools"
        attempt = _attempt(
            "t-2",
            index,
            model,
            protocol,
            reason,
            retry,
            status,
            ok,
            [entry],
            errors=errors,
            detail=detail,
        )
        attempts2.append(attempt)
        t.emit(1_100, "attempt_recorded", {"agent_id": "a-op-copy", "attempt": _dump(attempt)})
        t.budget(50, entry)
    result2 = _result(task2, entries2, "ok_after_escalation")
    t.emit(
        50,
        "task_result",
        {"agent_id": "a-op-copy", "result": _dump(result2), "label": "ok_after_escalation"},
    )
    t.release(50, budget2, "a-op-copy", "a-manager-1")

    # t-3: the menu. The first operator reports failure on Super and on Ultra (the top of
    # the ladder); the manager reassigns the task to the next operator for the role, whose
    # first Ultra call does not fit its allocation. A budget stop is not reassigned.
    menu = _agent(
        "a-op-menu",
        "operator",
        "copywriter",
        SUPER,
        "a-manager-1",
        operator_id="copywriter-super-01",
        skills=["prose-style"],
    )
    t.emit(200, "agent_hired", {"agent": _dump(menu)})
    budget3 = operator_budget("a-op-menu", "t-3")
    task3 = _task("t-3", "copywriter", [f"store://{RUN_ID}/results/t-1"], TASK_USD)
    t.emit(
        100,
        "task_assigned",
        {"task": _dump(task3), "agent_id": "a-op-menu", "operator_id": "copywriter-super-01"},
    )
    attempts3, entries3 = [], []
    ladder = ((SUPER, "first", None), (ULTRA, "escalation", "operator_reported_failure"))
    for index, (model, reason, retry) in enumerate(ladder):
        t.emit(
            150,
            "task_started",
            {"task_id": "t-3", "agent_id": "a-op-menu", "model": model, "attempt_index": index},
        )
        entry = t.charge(
            "operator",
            "t-3",
            model,
            1_200,
            300,
            Decimal("0.0005"),
            skills=["prose-style"],
            budget_id=budget3.id,
        )
        entries3.append(entry)
        attempt = _attempt(
            "t-3", index, model, "native_tools", reason, retry, "final", False, [entry]
        )
        attempts3.append(attempt)
        t.emit(1_000, "attempt_recorded", {"agent_id": "a-op-menu", "attempt": _dump(attempt)})
        t.budget(50, entry)
    result3 = _result(task3, entries3, "failed; stopped: top_of_ladder", status="failed")
    t.emit(
        50, "task_result", {"agent_id": "a-op-menu", "result": _dump(result3), "label": "failed"}
    )
    t.release(50, budget3, "a-op-menu", "a-manager-1")

    menu2 = _agent(
        "a-op-menu-2",
        "operator",
        "copywriter",
        ULTRA,
        "a-manager-1",
        operator_id="copywriter-ultra-01",
        skills=["prose-style"],
    )
    t.emit(200, "agent_hired", {"agent": _dump(menu2)})
    t.emit(
        50,
        "escalation",
        {
            "from_agent_id": "a-op-menu",
            "to_agent_id": "a-op-menu-2",
            "task_id": "t-3",
            "reason": "[synthetic] Operator copywriter-super-01 failed (top_of_ladder); "
            "the manager reassigns the task.",
        },
    )
    budget4 = operator_budget("a-op-menu-2", "t-3.2")
    task4 = _task("t-3.2", "copywriter", [f"store://{RUN_ID}/results/t-1"], TASK_USD)
    t.emit(
        100,
        "task_assigned",
        {"task": _dump(task4), "agent_id": "a-op-menu-2", "operator_id": "copywriter-ultra-01"},
    )
    t.emit(
        100,
        "task_started",
        {"task_id": "t-3.2", "agent_id": "a-op-menu-2", "model": ULTRA, "attempt_index": 0},
    )
    stop = t.refuse("operator", "t-3.2", ULTRA, 1_500, 1_200, budget4.id)
    attempt4 = _attempt(
        "t-3.2",
        0,
        ULTRA,
        "native_tools",
        "first",
        None,
        "budget_exhausted",
        False,
        [],
        errors=[f"(loop): ended with budget_exhausted: {stop}"],
        detail=str(stop),
    )
    t.emit(50, "attempt_recorded", {"agent_id": "a-op-menu-2", "attempt": _dump(attempt4)})
    t.emit(
        50,
        "budget_exhausted",
        {
            "agent_id": "a-op-menu-2",
            "level": "operator",
            "scope": stop.scope,
            "key": stop.key,
            "cap_usd": stop.cap_usd,
            "committed_usd": stop.committed_usd,
            "requested_usd": stop.requested_usd,
        },
    )
    result4 = _result(
        task4, [], "failed; stopped: budget_exhausted", status="failed", schema_valid=False
    )
    t.emit(
        50, "task_result", {"agent_id": "a-op-menu-2", "result": _dump(result4), "label": "failed"}
    )
    t.release(50, budget4, "a-op-menu-2", "a-manager-1")
    t.release(100, manager_budget, "a-manager-1", "a-director")

    audit_entry = t.charge(
        "auditor",
        "audit",
        ULTRA,
        2_500,
        200,
        Decimal("0.0035"),
        skills=["prose-style"],
        budget_id=auditor_budget.id,
    )
    audit = api.AuditVerdict(
        verdict="accepted",
        model=ULTRA,
        correction_cycles=0,
        checks=[
            api.AuditCheck(criterion="[synthetic] Covers the goal", passed=True),
            api.AuditCheck(criterion="[synthetic] Plain, specific prose", passed=True),
            api.AuditCheck(criterion="[synthetic] Sources listed", passed=True),
        ],
    )
    t.emit(1_500, "audit_result", {"audit": _dump(audit)})
    t.budget(50, audit_entry)
    t.release(50, auditor_budget, "a-auditor", "a-director")
    summary_entry = t.charge("director", "deliver", ULTRA, 2_000, 300, Decimal("0.0030"))
    t.budget(1_000, summary_entry)
    say(
        100,
        "director",
        "[synthetic] Done: research notes and website copy, audited and accepted. The menu "
        "is missing: its second operator's first call did not fit the task budget. See the "
        "delivery package.",
    )

    report = t.ledger.report(RUN_ID)
    assert report.held_usd == 0
    predicted = sum((e.usd_predicted for e in report.entries), ZERO_USD)
    package_url = f"/api/v1/runs/{RUN_ID}/package"
    t.emit(
        100,
        "run_finished",
        {
            "status": "finished",
            "partial": True,
            "spent_usd": report.spent_usd,
            "predicted_usd": predicted,
            "package_url": package_url,
        },
    )

    caps = api.RunCaps(run_usd=BUDGET_USD)
    run = api.RunView(
        run_id=RUN_ID,
        goal=GOAL,
        mode="recorded",
        recording_id=RECORDING_ID,
        simulated_case=True,
        status="finished",
        caps=caps,
        spent_usd=report.spent_usd,
        held_usd=report.held_usd,
        predicted_usd=predicted,
        created_at=START,
        finished_at=t.clock,
        events_url=f"/api/v1/runs/{RUN_ID}/events",
    )
    org = api.OrgChart(
        run_id=RUN_ID,
        mode="recorded",
        as_of_event_id=t.events[-1]["event"]["id"],
        nodes=[
            n.model_copy(update={"status": "failed" if n in (menu, menu2) else "done"})
            for n in (director, auditor, manager, researcher, copywriter, menu, menu2)
        ],
    )
    estimated = sum(e.usage_estimated for e in report.entries)
    ledger_view = api.LedgerView(
        run_id=RUN_ID,
        mode="recorded",
        caps=caps,
        spent_usd=report.spent_usd,
        held_usd=report.held_usd,
        predicted_usd=predicted,
        spent_by_level=dict(report.spent_by_level),
        usage_estimated_entries=estimated,
        entries=list(report.entries),
        stops=[
            api.CapStop(
                scope=s.scope,
                key=s.key,
                cap_usd=s.cap_usd,
                committed_usd=s.committed_usd,
                requested_usd=s.requested_usd,
            )
            for s in report.stops
        ],
    )
    tasks = api.TaskList(
        run_id=RUN_ID,
        mode="recorded",
        items=[
            api.TaskView(
                task=task1,
                agent_id="a-op-research",
                operator_id="researcher-lightning-01",
                status="ok",
                label="first_pass_ok",
                result=result1,
                attempts=[attempt1],
                tool_calls={"search": 1},
            ),
            api.TaskView(
                task=task2,
                agent_id="a-op-copy",
                operator_id="copywriter-lightning-01",
                status="ok",
                label="ok_after_escalation",
                result=result2,
                attempts=attempts2,
            ),
            api.TaskView(
                task=task3,
                agent_id="a-op-menu",
                operator_id="copywriter-super-01",
                status="failed",
                label="failed",
                result=result3,
                attempts=attempts3,
            ),
            api.TaskView(
                task=task4,
                agent_id="a-op-menu-2",
                operator_id="copywriter-ultra-01",
                status="failed",
                label="failed",
                result=result4,
                attempts=[attempt4],
            ),
        ],
    )
    package = api.DeliveryPackage(
        run_id=RUN_ID,
        mode="recorded",
        simulated_case=True,
        summary="[synthetic] A one-page site plan: research notes and the page copy. "
        "The menu is missing.",
        deliverables=[
            api.Deliverable(
                task_id="t-1",
                output_ref=result1.output_ref,
                title="[synthetic] Research notes",
                content={
                    "answer": "[synthetic] Three things neighbours look "
                    "for: opening hours, today's bread, how to order.",
                    "sources": ["https://example.com/synthetic-source"],
                },
            ),
            api.Deliverable(
                task_id="t-2",
                output_ref=result2.output_ref,
                title="[synthetic] Page copy",
                content={
                    "headline": "[synthetic] Fresh bread, around the corner",
                    "body": "[synthetic] Open 7 to 7. Order by phone.",
                },
            ),
        ],
        cost_report=api.CostReport(
            predicted_usd=predicted,
            real_usd=report.spent_usd,
            # A ratio, not money: the one number in the contract that stays a JSON number.
            prediction_error=float((report.spent_usd - predicted) / predicted),
            spent_by_level=dict(report.spent_by_level),
            usage_estimated_entries=estimated,
        ),
        contracts=[
            api.ContractRecord(task=task1, result=result1),
            api.ContractRecord(task=task2, result=result2),
            api.ContractRecord(task=task3, result=result3),
            api.ContractRecord(task=task4, result=result4),
        ],
        decisions=[
            "[synthetic] Picked the plan with one manager and three operator tasks.",
            "[synthetic] t-2 moved from Lightning to Super after an interrupted "
            "stream; that call was charged its full reservation.",
            "[synthetic] t-3 failed on Super and on Ultra; the manager reassigned it to "
            "copywriter-ultra-01 as t-3.2.",
            "[synthetic] t-3.2 stopped on its budget: one Ultra call did not fit its "
            "USD 0.003 allocation, so the menu is missing.",
        ],
        audit=audit,
    )
    modes = _modes(live_available=True)
    bundle = {
        "_fixture": FIXTURE_NOTE,
        "modes": _dump(modes),
        "run": _dump(run),
        "runs": _dump(api.RunList(items=[run])),
        "org": _dump(org),
        "ledger": _dump(ledger_view),
        "messages": _dump(api.ChatMessageList(run_id=RUN_ID, mode="recorded", items=messages)),
        "tasks": _dump(tasks),
        "package": _dump(package),
    }
    replay = {"_fixture": FIXTURE_NOTE, "run_id": RUN_ID, "events": t.events}
    return bundle, replay


DAILY_CAP_DETAIL = "[synthetic] The daily live budget is used up. Recorded runs still work."
VISITOR_DETAIL = "[synthetic] You already used your live run for today. Recorded runs still work."


def _modes(
    live_available: bool,
    refusal: str | None = None,
    spent_today: Decimal = Decimal("0.42"),
    visitor_runs: int = 0,
    detail: str = DAILY_CAP_DETAIL,
):
    return api.ModesView(
        default_mode="recorded",
        modes=[
            api.ModeAvailability(mode="recorded", available=True),
            api.ModeAvailability(
                mode="live",
                available=live_available,
                refusal=refusal,
                detail="" if live_available else detail,
            ),
        ],
        live_caps=api.LiveCaps(
            max_usd_per_run=Decimal("0.25"),
            max_usd_per_day=Decimal("3.00"),
            spent_usd_today=spent_today,
            max_runs_per_visitor_per_day=1,
            visitor_runs_today=visitor_runs,
        ),
        recordings=[
            api.RecordingSummary(
                recording_id=RECORDING_ID,
                title="[synthetic] Corner bakery website",
                goal=GOAL,
                simulated_case=True,
                spent_usd=ZERO_USD,
            )
        ],
    )


def live_refused() -> dict[str, Any]:
    request = api.CreateRunRequest(
        mode="live", goal="[synthetic] Draft a price list.", budget_usd=Decimal("0.20")
    )
    error = api.ErrorResponse(
        error=api.ErrorBody(
            code="live_refused",
            message="[synthetic] Live runs are paused: the daily live budget is used up.",
            details={
                "refusal": "daily_cap_reached",
                "max_usd_per_day": "3.000000",
                "spent_usd_today": "3.000000",
                "retry": "recorded",
            },
            request_id="req-synthetic-1",
        )
    )
    run_id = "run_3e9d0b6a51"
    ts = START + timedelta(hours=1)
    stream = [
        {
            "delay_ms": 0,
            "event": {
                "id": f"{run_id}:1",
                "seq": 1,
                "run_id": run_id,
                "mode": "live",
                "ts": ts.isoformat(),
                "type": "mode_notice",
                "payload": {
                    "notice": "live_refused",
                    "mode": "live",
                    "refusal": "daily_cap_reached",
                    "detail": "[synthetic] The daily live budget ran out before this "
                    "run started. Nothing was spent.",
                },
            },
        },
        {
            "delay_ms": 20,
            "event": {
                "id": f"{run_id}:2",
                "seq": 2,
                "run_id": run_id,
                "mode": "live",
                "ts": (ts + timedelta(milliseconds=20)).isoformat(),
                "type": "run_failed",
                "payload": {
                    "error": {
                        "code": "live_refused",
                        "message": "[synthetic] Live budget for today is used up.",
                        "details": {"refusal": "daily_cap_reached"},
                    },
                    "partial": False,
                    "spent_usd": "0.000000",
                },
            },
        },
    ]
    for item in stream:
        api.SSE_EVENT_ADAPTER.validate_python(item["event"])
    visitor_error = api.ErrorResponse(
        error=api.ErrorBody(
            code="live_refused",
            message=VISITOR_DETAIL,
            details={
                "refusal": "visitor_limit_reached",
                "max_runs_per_visitor_per_day": 1,
                "visitor_runs_today": 1,
                "retry": "recorded",
            },
            request_id="req-synthetic-2",
        )
    )
    return {
        "_fixture": FIXTURE_NOTE,
        "request": _dump(request),
        "status": 429,
        "response": _dump(error),
        "modes": _dump(
            _modes(live_available=False, refusal="daily_cap_reached", spent_today=Decimal("3.00"))
        ),
        "refused_after_creation": {"run_id": run_id, "events": stream},
        "visitor_limit": {
            "status": 429,
            "response": _dump(visitor_error),
            "modes": _dump(
                _modes(
                    live_available=False,
                    refusal="visitor_limit_reached",
                    visitor_runs=1,
                    detail=VISITOR_DETAIL,
                )
            ),
        },
    }


def files() -> dict[str, str]:
    bundle, replay = recorded_run()

    def text(data: Any) -> str:
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    return {
        "recorded_run.json": text(bundle),
        "recorded_run.events.json": text(replay),
        "live_refused.json": text(live_refused()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    wanted = files()
    if args.check:
        stale = [
            n
            for n, t in wanted.items()
            if not (OUT_DIR / n).exists() or (OUT_DIR / n).read_text("utf-8") != t
        ]
        print(f"stale: {stale}" if stale else f"{len(wanted)} fixtures up to date")
        return 1 if stale else 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in wanted.items():
        (OUT_DIR / name).write_text(content, encoding="utf-8")
    print(f"wrote {len(wanted)} fixtures to {OUT_DIR.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
