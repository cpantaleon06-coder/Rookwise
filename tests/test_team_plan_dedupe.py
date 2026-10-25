"""The director's plan without tasks that repeat an earlier task's (role, source), in any
block, and without the blocks that leaves empty (inc-05 run2 read orders-api.log twice and
went from 58 to 91 slices). Stub transport; no network."""

from team_stub import (
    GOOD_CLAIM,
    TeamHandler,
    block,
    diagnosis_reply,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.team import BudgetPolicy
from rookwise.team.config import load_budget_policy
from rookwise.team.models import Plan, dedupe_plan


def _task(role, source_id):
    return {"role": role, "source_id": source_id, "instruction": f"[stub] Read {source_id}."}


def _plan(*blocks):
    return Plan.model_validate(
        {
            "summary": "[stub]",
            "blocks": [{"goal": f"[stub] b{i}", "tasks": tasks} for i, tasks in enumerate(blocks)],
        }
    )


def _pairs(plan):
    return [[(t.role, t.source_id) for t in b.tasks] for b in plan.blocks]


def test_the_inc05_run2_shape_loses_its_repeated_log_task():
    plan = _plan(
        [_task("log-reader", "ticket.md")],
        [_task("deploy-diff-reader", "deploy.diff")],
        [
            _task("log-reader", "logs/orders-api.log"),
            _task("log-reader", "logs/orders-api.log"),
            _task("log-reader", "logs/notify-worker.jsonl"),
            _task("log-reader", "logs/pg-proxy.log"),
        ],
        [_task("metrics-reader", "metrics.csv")],
        [_task("log-reader", "runbook.md")],
    )
    deduped, dropped = dedupe_plan(plan)
    assert dropped == 1 and len(deduped.blocks) == 5
    assert _pairs(deduped)[2] == [
        ("log-reader", "logs/orders-api.log"),
        ("log-reader", "logs/notify-worker.jsonl"),
        ("log-reader", "logs/pg-proxy.log"),
    ]
    assert len(plan.blocks[2].tasks) == 4  # the original plan is not changed


def test_a_repeat_in_another_block_is_dropped_and_an_emptied_block_removed():
    plan = _plan(
        [_task("log-reader", "a.log"), _task("metrics-reader", "m.csv")],
        [_task("log-reader", "a.log")],
        [_task("metrics-reader", "a.log"), _task("log-reader", "m.csv")],
    )
    deduped, dropped = dedupe_plan(plan)
    assert dropped == 1
    assert [b.goal for b in deduped.blocks] == ["[stub] b0", "[stub] b2"]
    # The same source under another role, or another source, is not a repeat.
    assert _pairs(deduped)[1] == [("metrics-reader", "a.log"), ("log-reader", "m.csv")]


def test_a_plan_without_repeats_is_left_as_is():
    plan = _plan([_task("log-reader", "a.log")], [_task("log-reader", "b.log")])
    assert dedupe_plan(plan) == (plan, 0)


def test_the_switch_is_config_and_on():
    assert load_budget_policy().drop_duplicate_plan_tasks is True


def _run(director, policy, operators=1):
    handler = TeamHandler(
        director=director,
        operator=[findings_reply(GOOD_CLAIM) for _ in range(operators)],
        manager=[summary_reply(), summary_reply()],
        diagnosis=[diagnosis_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5", policy=policy)
    return team, handler


def test_a_team_run_reads_each_role_and_source_once():
    team, handler = _run([plan_reply(block(3), block(2))], BudgetPolicy())
    assert team.duplicate_tasks_dropped == 4 and handler.calls["operator"] == 1
    assert len(team.plan.blocks) == 1 and len(team.blocks) == 1
    assert any("those tasks were dropped" in note for note in team.notes)


def test_dropping_repeats_can_bring_a_plan_within_the_limits():
    six = plan_reply(*[block(1) for _ in range(6)])  # six blocks, all the same task
    team, handler = _run([six], BudgetPolicy())
    assert team.status == "finished" and team.plan_repairs == 0
    assert team.duplicate_tasks_dropped == 5 and handler.calls["director"] == 1


def test_with_the_switch_off_the_repeats_stay():
    policy = BudgetPolicy(drop_duplicate_plan_tasks=False)
    team, handler = _run([plan_reply(block(2))], policy, operators=2)
    assert team.duplicate_tasks_dropped == 0 and handler.calls["operator"] == 2
