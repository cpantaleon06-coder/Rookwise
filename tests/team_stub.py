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
from rookwise.team.flow import DIAGNOSIS_PROMPT, DIRECTOR_PROMPT, MANAGER_PROMPT, OPERATOR_PROMPT

ULTRA, LIGHTNING = "nemotron-3-ultra", "nemotron-3.5-lightning"
RUN_ID = "run_team01"
GOAL = "[stub] Describe the sample widget from the sources."
ROUTES = (
    ("director", DIRECTOR_PROMPT),
    ("diagnosis", DIAGNOSIS_PROMPT),
    ("manager", MANAGER_PROMPT),
    ("auditor", AUDITOR_PROMPT),
    ("operator", OPERATOR_PROMPT),
)


def skills_config(manager_max_tokens: int = 8192, operator_max_tokens: int = 256) -> dict[str, Any]:
    """Every team agent on Ultra, so a worst case is mostly max_tokens x USD 3 per 1M."""
    return {
        "skills": {"stub-notes": {"max_tokens": 100}},
        "roles": {
            "stub-director": {
                "level": "director",
                "model": ULTRA,
                "skills": [],
                "max_skill_tokens": 0,
                "max_output_tokens": 256,
            },
            "stub-manager": {
                "level": "manager",
                "model": ULTRA,
                "skills": [],
                "max_skill_tokens": 0,
                "max_output_tokens": manager_max_tokens,
            },
            "stub-auditor": {
                "level": "auditor",
                "model": ULTRA,
                "skills": [],
                "max_skill_tokens": 0,
                "max_output_tokens": 256,
            },
            "stub-operator": {
                "model": LIGHTNING,
                "skills": ["stub-notes"],
                "max_skill_tokens": 100,
                "max_output_tokens": operator_max_tokens,
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
UNCITED_CLAIM = {"claim_id": "c2", "text": "[stub] The widget is heavy.", "citations": []}
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


def block(tasks: int = 1, source_id: str = "src-a") -> dict[str, Any]:
    task = {
        "role": "stub-operator",
        "source_id": source_id,
        "instruction": "[stub] Report what the sources say.",
    }
    return {"goal": "[stub] A block of work.", "tasks": [task] * tasks}


def plan_reply(*blocks: dict[str, Any], prompt: int = 100) -> bytes:
    plan = {"summary": "[stub] A plan.", "blocks": list(blocks)}
    return text_reply(_payload(plan), prompt=prompt)


def findings_payload(*claims: dict[str, Any], status: str = "ok") -> str:
    output = {"summary": "[stub] Findings.", "claims": list(claims)}
    return _payload(output, status=status, notes="" if status == "ok" else "[stub]")


def findings_reply(*claims: dict[str, Any], status: str = "ok") -> bytes:
    return text_reply(findings_payload(*claims, status=status))


def summary_reply(status: str = "ok") -> bytes:
    notes = "" if status == "ok" else "[stub]"
    return text_reply(_payload({"summary": "[stub] The block is done."}, status, notes))


def diagnosis_payload(
    *claims: dict[str, Any],
    root: tuple[str, ...] | None = None,
    category: str = "bad_config",
) -> str:
    claims = claims or (GOOD_CLAIM,)
    output = {
        "root_cause": "[stub] The widget weighs 12 units.",
        "category": category,
        "claims": list(claims),
        "root_cause_claim_ids": list(root or (claims[0]["claim_id"],)),
        "remediation_plan": [
            {
                "action": "[stub] Check the widget.",
                "why": "[stub] It is the cause.",
                "risk": "[stub] None known.",
                "reversible": True,
            }
        ],
    }
    return _payload(output)


def diagnosis_reply(*claims: dict[str, Any], **kwargs: Any) -> bytes:
    return text_reply(diagnosis_payload(*claims, **kwargs))


def judgment_reply(verdict: str = "accepted") -> bytes:
    check = {"criterion": "[stub] Meets the goal", "passed": verdict == "accepted", "note": ""}
    return text_reply(_payload({"verdict": verdict, "checks": [check]}))


class TeamHandler:
    """Answers each request with the next scripted reply for the agent that sent it."""

    def __init__(self, **replies: list[bytes]) -> None:
        # The director's diagnosis defaults to one stub diagnosis on BUNDLE.
        replies.setdefault("diagnosis", [diagnosis_reply()])
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
    bundle=None,
    slicing=None,
    context_sources=(),
    ledger=None,
    store=None,
    stop_after=None,
    baseline=None,
):
    book = ledger if ledger is not None else InMemoryLedger()
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
                store=store if store is not None else InMemoryStore(),
                catalog=catalog or CATALOG,
                evidence=bundle or BUNDLE,
                slicing=slicing,
                context_sources=context_sources,
                skills_config=config or skills_config(),
                skills_dir=SKILLS_DIR,
                policy=policy,
                clock=ticking_clock(),
                stop_after=stop_after,
                baseline=baseline,
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
    """Every `allocated` matches a ledger allocation, in order, and each `released` comes
    after an `allocated` of the same agent (a manager has two: its block and its
    operators' pool, which brackets the block's tasks); every `budget_exhausted` is a stop
    the ledger recorded."""
    report = book.report(RUN_ID)
    allocations = [e.payload for e in events if e.type == "budget_allocation"]
    allocated = [p.usd for p in allocations if p.action == "allocated"]
    assert allocated == [node.usd for node in report.allocations]
    released = sorted(p.usd for p in allocations if p.action == "released")
    assert released == sorted(node.released_usd for node in report.allocations if node.closed)
    open_count: dict[str, int] = {}
    for event in events:
        if event.type == "budget_allocation":
            agent_id = event.payload.agent_id
            change = 1 if event.payload.action == "allocated" else -1
            open_count[agent_id] = open_count.get(agent_id, 0) + change
            assert open_count[agent_id] >= 0, event.id
    hired = {e.payload.agent.agent_id: e.payload.agent for e in events if e.type == "agent_hired"}
    for index, event in enumerate(events):
        if event.type == "task_assigned":
            manager = hired[event.payload.agent_id].parent_id
            before = [
                e
                for e in events[:index]
                if e.type == "budget_allocation" and e.payload.agent_id == manager
            ]
            # A manager's block and its pool are open while the task runs, plus the pool's
            # top-up once the director has drawn one; a baseline's operators work under
            # the director, out of its one pool.
            expected = (1,) if hired[manager].level == "director" else (2, 3)
            assert sum(1 if e.payload.action == "allocated" else -1 for e in before) in expected
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
    within it."""
    report = book.report(RUN_ID)
    assert report.held_usd == 0
    for node in report.allocations:
        assert node.closed, node.id
        children = [a.spent_usd for a in report.allocations if a.parent == node.id]
        assert sum(children, Decimal(0)) <= node.spent_usd <= node.usd, node.id
        assert node.spent_usd + node.released_usd == node.usd, node.id
    # Blocks are allocated one after another and reuse what earlier ones left, so the
    # cap bounds what was spent through the top-level allocations.
    top = [a.spent_usd for a in report.allocations if a.parent is None]
    assert sum(top, Decimal(0)) <= report.caps.run_usd
    assert book.free(RUN_ID) + report.spent_usd == report.caps.run_usd
