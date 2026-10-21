"""`run_team(stop_after="plan")` ends the run after the director's plan. Stub transport."""

from team_stub import TeamHandler, block, plan_reply, run_stub_team


def test_the_run_ends_after_the_plan_with_no_other_call():
    # Only a plan reply is scripted: any other call fails the handler.
    handler = TeamHandler(director=[plan_reply(block(1), block(2))], diagnosis=[])
    team, book = run_stub_team(handler, run_usd="0.5", stop_after="plan")
    assert handler.calls["director"] == 1 and sum(handler.calls.values()) == 1
    assert (team.status, team.partial) == ("cancelled", True)
    assert team.plan is not None and len(team.plan.blocks) == 2 and team.blocks == []
    report = book.report(team.run_id)
    assert [e.task_id for e in report.entries] == ["plan"] and report.held_usd == 0
    assert not report.allocations  # no budget was split
    assert team.events[-1].type == "run_finished"
    assert team.events[-1].payload.status == "cancelled"
