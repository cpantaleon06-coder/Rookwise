"""A failed task is not reassigned to an operator whose first call its remaining limit
cannot cover: the ledger would refuse that call before it starts. Stub transport."""

from harness_support import text_reply
from team_stub import (
    TeamHandler,
    block,
    findings_reply,
    judgment_reply,
    operator,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.team import BudgetPolicy

ULTRA = "nemotron-3-ultra"
CUT = text_reply('{"status": "ok", "output": {"summary": "[st', reason="length")
CATALOG = [operator("stub-op-a", "0.001"), operator("stub-op-u", "0.002", model=ULTRA)]


def _run(policy):
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[CUT, findings_reply()],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5", catalog=CATALOG, policy=policy)
    return team, book, handler


def test_a_reassignment_the_limit_cannot_cover_is_not_made():
    # The limit is one first reservation on Lightning; Ultra's first call costs far more.
    team, book, handler = _run(
        BudgetPolicy(task_limit_first_rung_reservations=1, task_limit_next_rung_reservations=0)
    )
    (task,) = team.blocks[0].tasks
    assert task.status == "failed" and task.assignments == ["t-1"]
    assert handler.calls["operator"] == 1
    assert sum(e.type == "task_assigned" for e in team.events) == 1
    (note,) = [n for n in team.notes if n.startswith("t-1:")]
    assert "is left of the task's limit, less than stub-op-u's first call" in note
    assert note.endswith("; escalated to the director.")
    assert not [s for s in book.report(team.run_id).stops if s.scope == "task"]


def test_a_reassignment_the_limit_covers_is_still_made():
    team, _, handler = _run(BudgetPolicy(task_limit_first_rung_reservations=40))
    (task,) = team.blocks[0].tasks
    assert task.assignments == ["t-1", "t-1.2"] and handler.calls["operator"] == 2
