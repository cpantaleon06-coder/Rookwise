"""A plan over the size limits gets one targeted repair: the repair request states the
limits and asks to merge sources; still too large, the run fails as before. The plan
prompt states the limits up front. Stub transport and a 6-block reply; no network."""

from team_stub import (
    GOOD_CLAIM,
    RUN_ID,
    TeamHandler,
    assert_contract_order,
    block,
    diagnosis_reply,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.team import BudgetPolicy
from rookwise.team.flow import DIRECTOR_PROMPT, plan_prompt

SIX = plan_reply(*[block(1) for _ in range(6)])  # 6 blocks, the stub's one source each


def _director_bodies(handler):
    return [b for b in handler.bodies if b["messages"][0]["content"].startswith(DIRECTOR_PROMPT)]


def test_the_plan_prompt_states_the_limits_up_front():
    prompt = plan_prompt(BudgetPolicy(max_blocks=5, max_tasks_per_block=5))
    assert prompt.startswith(DIRECTOR_PROMPT)
    assert "at most 5 blocks, each with at most 5 tasks" in prompt
    assert "one block may hold tasks for several sources" in prompt


def test_a_six_block_plan_is_repaired_once_and_the_run_goes_on():
    handler = TeamHandler(
        director=[SIX, plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        diagnosis=[diagnosis_reply()],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5")
    assert team.status == "finished" and team.plan_repairs == 1
    assert len(team.plan.blocks) == 1 and len(team.blocks) == 1
    first, repair = _director_bodies(handler)
    assert "at most 5 blocks, each with at most 5 tasks" in first["messages"][0]["content"]
    request = repair["messages"][-1]["content"]
    assert "PLAN TOO LARGE: it has 6 blocks (tasks per block: 1, 1, 1, 1, 1, 1)" in request
    assert "at most 5 blocks, each with at most 5 tasks" in request
    assert "Merge sources into fewer blocks" in request
    assert "Your plan:" in request
    tasks = [e.task_id for e in book.report(RUN_ID).entries if e.level == "director"]
    assert tasks[:2] == ["plan", "plan-repair"]
    assert any("one targeted repair" in note for note in team.notes)
    assert_contract_order(team, book)


def test_a_repair_still_too_large_fails_as_today():
    handler = TeamHandler(director=[SIX, SIX])
    team, book = run_stub_team(handler, run_usd="0.5")
    assert team.status == "failed" and handler.calls["director"] == 2  # exactly one repair
    failed = next(e.payload for e in team.events if e.type == "run_failed")
    assert failed.error.code == "plan_too_large"
    assert failed.error.details == {"max_blocks": 5, "max_tasks_per_block": 5, "repaired": True}
    assert book.report(RUN_ID).allocations == ()
    assert_contract_order(team, book)


def test_a_repair_with_no_valid_plan_fails_as_plan_too_large():
    # An empty plan fails validation; the repair call itself gets its usual re-tries
    # (escalation.max_repairs, 2) on Ultra, the top of the ladder.
    handler = TeamHandler(director=[SIX, plan_reply(), plan_reply(), plan_reply()])
    team, _ = run_stub_team(handler, run_usd="0.5")
    assert handler.calls["director"] == 4
    failed = next(e.payload for e in team.events if e.type == "run_failed")
    assert failed.error.code == "plan_too_large"
    assert any("The plan repair produced no valid plan" in note for note in team.notes)


def test_a_plan_within_the_limits_gets_no_repair():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        diagnosis=[diagnosis_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    assert team.plan_repairs == 0 and handler.calls["director"] == 1


def test_the_repair_also_runs_for_a_plan_only_run():
    handler = TeamHandler(director=[SIX, plan_reply(block(1))])
    team, _ = run_stub_team(handler, run_usd="0.5", stop_after="plan")
    assert team.status == "cancelled" and team.plan_repairs == 1
    assert len(team.plan.blocks) == 1
