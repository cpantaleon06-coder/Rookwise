"""Stubs for the team tests: a role config, an operator catalog, an evidence bundle,
scripted replies per agent, and a transport that routes each request to the agent that
sent it (by the base prompt its system message starts with). Neutral placeholder text,
no network.
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from harness_support import TEST_KEY, FakeClock, text_reply
from operator_stub import SKILLS_DIR

from rookwise.api.models import TERMINAL_EVENTS
from rookwise.evidence import EvidenceBundle
from rookwise.harness import Harness, load_config
from rookwise.ledger import Caps, InMemoryLedger
from rookwise.runner import OperatorSpec
from rookwise.store import InMemoryStore
from rookwise.team import run_team
from rookwise.team.auditor import AUDITOR_PROMPT
from rookwise.team.flow import DIRECTOR_PROMPT, MANAGER_PROMPT, OPERATOR_PROMPT

ULTRA, LIGHTNING = "nemotron-3-ultra", "nemotron-3.5-lightning"
RUN_ID = "run_team01"
GOAL = "[stub] Describe the sample widget from the sources."
ROUTES = (
    ("director", DIRECTOR_PROMPT),
    ("manager", MANAGER_PROMPT),
    ("auditor", AUDITOR_PROMPT),
    ("operator", OPERATOR_PROMPT),
)


def skills_config(manager_max_tokens: int = 8192) -> dict[str, Any]:
    """Every team agent on Ultra, so a worst case is mostly max_tokens x USD 3 per 1M."""
    return {
        "skills": {"stub-notes": {"max_tokens": 100}},
        "roles": {
            "stub-director": {
                "level": "director",
                "model": ULTRA,
                "skills": [],
                "max_skill_tokens": 0,
                "max_tokens": 256,
            },
            "stub-manager": {
                "level": "manager",
                "model": ULTRA,
                "skills": [],
                "max_skill_tokens": 0,
                "max_tokens": manager_max_tokens,
            },
            "stub-auditor": {
                "level": "auditor",
                "model": ULTRA,
                "skills": [],
                "max_skill_tokens": 0,
                "max_tokens": 256,
            },
            "stub-operator": {
                "model": LIGHTNING,
                "skills": ["stub-notes"],
                "max_skill_tokens": 100,
            },
        },
    }


def operator(operator_id: str, price: str, **overrides: Any) -> OperatorSpec:
    data: dict[str, Any] = {
        "operator_id": operator_id,
        "role": "stub-operator",
        "model": LIGHTNING,
        "price_per_task_est_usd": Decimal(price),
        "avg_latency_s": 5,
        "reputation": 0.5,
        "tools": [],
        "skills": ["stub-notes"],
        "input_schema": "task_v1",
        "output_schema": "result_v1",
        "max_tokens": 256,
    }
    return OperatorSpec.model_validate(data | overrides)


CATALOG = [operator("stub-op-b", "0.002"), operator("stub-op-a", "0.001")]
BUNDLE = EvidenceBundle(
    sources={
        "src-a": "Sample record one: the widget weighs 12 units.\n"
        "Sample record two: the widget is blue.\n"
    }
)
GOOD_CLAIM = {
    "claim_id": "c1",
    "text": "[stub] The widget weighs 12 units.",
    "citations": [
        {
            "source_id": "src-a",
            "line_start": 1,
            "line_end": 1,
            "quote": "the widget weighs 12 units.",
        }
    ],
}
FABRICATED_CLAIM = {
    "claim_id": "c2",
    "text": "[stub] The widget weighs 15 units.",
    "citations": [
        {
            "source_id": "src-a",
            "line_start": 1,
            "line_end": 1,
            "quote": "the widget weighs 15 units.",
        }
    ],
}


def _payload(output: Any, status: str = "ok", notes: str = "") -> str:
    return json.dumps({"status": status, "output": output, "notes": notes})


def block(tasks: int = 1) -> dict[str, Any]:
    task = {"role": "stub-operator", "instruction": "[stub] Report what the sources say."}
    return {"goal": "[stub] A block of work.", "tasks": [task] * tasks}


def plan_reply(*blocks: dict[str, Any], prompt: int = 100) -> bytes:
    plan = {"summary": "[stub] A plan.", "blocks": list(blocks)}
    return text_reply(_payload(plan), prompt=prompt)


def findings_reply(*claims: dict[str, Any], status: str = "ok") -> bytes:
    output = {"summary": "[stub] Findings.", "claims": list(claims)}
    return text_reply(_payload(output, status=status, notes="" if status == "ok" else "[stub]"))


def summary_reply(status: str = "ok") -> bytes:
    notes = "" if status == "ok" else "[stub]"
    return text_reply(_payload({"summary": "[stub] The block is done."}, status, notes))


def judgment_reply(verdict: str = "accepted") -> bytes:
    check = {"criterion": "[stub] Meets the goal", "passed": verdict == "accepted", "note": ""}
    return text_reply(_payload({"verdict": verdict, "checks": [check]}))


class TeamHandler:
    """Answers each request with the next scripted reply for the agent that sent it."""

    def __init__(self, **replies: list[bytes]) -> None:
        self.replies = {kind: list(replies.get(kind, [])) for kind, _ in ROUTES}
        self.calls = {kind: 0 for kind, _ in ROUTES}
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        system = body["messages"][0]["content"]
        kind = next(kind for kind, prompt in ROUTES if system.startswith(prompt))
        if not self.replies[kind]:
            raise AssertionError(f"unexpected {kind} call")
        self.calls[kind] += 1
        return httpx.Response(
            200, content=self.replies[kind].pop(0), headers={"content-type": "text/event-stream"}
        )

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def ticking_clock():
    start = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
    count = iter(range(1_000_000))
    return lambda: start + timedelta(milliseconds=next(count))


def run_stub_team(
    handler: TeamHandler | None,
    *,
    run_usd: str,
    policy=None,
    catalog=None,
    config=None,
    harness_config=None,
    cassette=None,
):
    book = InMemoryLedger()
    book.open_run(RUN_ID, Caps(run_usd=Decimal(run_usd)))
    replay = cassette is not None and cassette.mode == "replay"

    async def main():
        harness = Harness(
            book,
            config=harness_config or load_config(env={}),
            api_key=None if replay else TEST_KEY,
            transport=None if handler is None else handler.transport(),
            clock=FakeClock(),
            rng=random.Random(0),
            cassette=cassette,
        )
        async with harness:
            return await run_team(
                GOAL,
                run_id=RUN_ID,
                harness=harness,
                store=InMemoryStore(),
                catalog=catalog or CATALOG,
                evidence=BUNDLE,
                skills_config=config or skills_config(),
                skills_dir=SKILLS_DIR,
                policy=policy,
                clock=ticking_clock(),
            )

    return asyncio.run(main()), book


# -- checks shared by the tests --------------------------------------------------------


def assert_contract_order(team, book) -> None:
    """The ordering rules of docs/api.md ("Ordering and idempotency") on a team run."""
    events = team.events
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert all(e.id == f"{RUN_ID}:{e.seq}" and e.run_id == RUN_ID for e in events)
    assert [e.ts for e in events] == sorted(e.ts for e in events)
    assert events[0].type == "run_started" and events[-1].type in TERMINAL_EVENTS
    assert sum(e.type in TERMINAL_EVENTS for e in events) == 1
    hired: set[str] = set()
    for event in events:
        payload = event.payload
        if event.type == "agent_hired":
            parent = payload.agent.parent_id
            assert parent is None or parent in hired, event.id
            hired.add(payload.agent.agent_id)
        for name in ("agent_id", "parent_agent_id", "from_agent_id", "to_agent_id"):
            agent_id = getattr(payload, name, None)
            assert agent_id is None or agent_id in hired, (event.id, name)
    # For a task: task_assigned, then per attempt task_started, attempt_recorded and the
    # attempt's budget updates, then budget_exhausted if the operator stopped on its
    # budget, then task_result.
    for index, event in enumerate(events):
        if event.type != "task_assigned":
            continue
        task_id, agent_id = event.payload.task.task_id, event.payload.agent_id
        allowed = ("task_started", "attempt_recorded", "budget_update", "budget_exhausted")
        for later in events[index + 1 :]:
            if later.type == "task_result":
                assert later.payload.result.task_id == task_id
                break
            assert later.type in allowed, later.id
            if later.type == "task_started":
                assert later.payload.task_id == task_id
            if later.type == "attempt_recorded":
                assert later.payload.attempt.task_id == task_id
            if later.type == "budget_update":
                assert later.payload.entry.task_id == task_id
            if later.type == "budget_exhausted":
                assert later.payload.agent_id == agent_id
        else:
            raise AssertionError(f"no task_result for {task_id}")
    _assert_allocation_events(events, book)


def _assert_allocation_events(events, book) -> None:
    """One `allocated` and at most one `released` per agent, in that order, matching the
    ledger's allocations; an operator's allocation brackets its task; every
    `budget_exhausted` is a stop the ledger recorded."""
    report = book.report(RUN_ID)
    position: dict[tuple[str, str], int] = {}
    for index, event in enumerate(events):
        if event.type == "budget_allocation":
            key = (event.payload.action, event.payload.agent_id)
            assert key not in position, event.id
            position[key] = index
    for (action, agent_id), index in position.items():
        if action == "released":
            assert position[("allocated", agent_id)] < index, agent_id
    allocations = [e.payload for e in events if e.type == "budget_allocation"]
    allocated = [p.usd for p in allocations if p.action == "allocated"]
    assert allocated == [node.usd for node in report.allocations]
    released = sorted(p.usd for p in allocations if p.action == "released")
    assert released == sorted(node.released_usd for node in report.allocations if node.closed)
    for index, event in enumerate(events):
        if event.type == "task_assigned":
            agent_id = event.payload.agent_id
            result = next(
                i
                for i, e in enumerate(events)
                if e.type == "task_result" and e.payload.agent_id == agent_id
            )
            assert position[("allocated", agent_id)] < index < result
            assert position[("released", agent_id)] > result
    stops = {(stop.scope, stop.key) for stop in report.stops}
    for event in events:
        if event.type == "budget_exhausted":
            assert (event.payload.scope, event.payload.key) in stops, event.id
    # One budget update per charged ledger entry, in charge order, with absolute totals.
    report = book.report(RUN_ID)
    updates = [e.payload for e in events if e.type == "budget_update"]
    assert [u.entry for u in updates] == list(report.entries)
    if updates:
        assert updates[-1].spent_usd == report.spent_usd


def assert_budget_tree(book) -> None:
    """Every allocation closed, its unspent part released, and what its children spent
    within it. (Operator allocations are opened one after another, each closed before
    the next, so only the top level is held all at once.)"""
    report = book.report(RUN_ID)
    assert report.held_usd == 0
    for node in report.allocations:
        assert node.closed, node.id
        children = [a.spent_usd for a in report.allocations if a.parent == node.id]
        assert sum(children, Decimal(0)) <= node.spent_usd <= node.usd, node.id
        assert node.spent_usd + node.released_usd == node.usd, node.id
    top = [a.usd for a in report.allocations if a.parent is None]
    assert sum(top, Decimal(0)) <= report.caps.run_usd
    assert book.free(RUN_ID) + report.spent_usd == report.caps.run_usd
