"""The team hierarchy (core/team) on scripted stubs and a cassette. No network.

Budgets are chosen so the case under test does not depend on the size of a prompt: a
level that must run out of budget gets less than its output tokens alone would cost
(every team agent is on Ultra, USD 3 per 1M output tokens), and the other levels get
several times what they need.
"""

import dataclasses
from decimal import Decimal

import pytest
from team_stub import (
    BUNDLE,
    FABRICATED_CLAIM,
    GOOD_CLAIM,
    RUN_ID,
    ULTRA,
    TeamHandler,
    assert_budget_tree,
    assert_contract_order,
    block,
    findings_reply,
    judgment_reply,
    operator,
    plan_reply,
    run_stub_team,
    skills_config,
    summary_reply,
)

from rookwise.harness import Cassette, load_config
from rookwise.harness.config import EscalationConfig
from rookwise.money import ZERO_USD
from rookwise.team import BudgetPolicy, load_team_roles

D = Decimal


def _types(team):
    return [e.type for e in team.events]


def _payloads(team, event_type):
    return [e.payload for e in team.events if e.type == event_type]


def _no_ladder():
    """No repairs and no model ladder: an operator's failure reaches its manager at once."""
    return dataclasses.replace(load_config(env={}), escalation=EscalationConfig(0, {}))


def test_a_normal_run_goes_through_every_level():
    handler = TeamHandler(
        director=[plan_reply(block(1), block(2))],
        operator=[findings_reply(GOOD_CLAIM) for _ in range(3)],
        manager=[summary_reply(), summary_reply()],
        auditor=[judgment_reply("accepted")],
    )
    team, book = run_stub_team(handler, run_usd="0.5")
    assert (team.status, team.partial, team.notes) == ("finished", False, [])
    assert [b.status for b in team.blocks] == ["ok", "ok"]
    assert [t.task_id for b in team.blocks for t in b.tasks] == ["t-1", "t-2", "t-3"]
    assert all(
        t.status == "ok" and t.operator_ids == ["stub-op-a"] for b in team.blocks for t in b.tasks
    )
    assert team.audit.verdict == "accepted" and team.evidence.all_supported
    assert team.evidence.citations_total == 3
    assert handler.calls == {"director": 1, "manager": 2, "auditor": 1, "operator": 3}
    hired = [p.agent for p in _payloads(team, "agent_hired")]
    assert [(a.agent_id, a.level, a.parent_id) for a in hired] == [
        ("a-director", "director", None),
        ("a-manager-b-1", "manager", "a-director"),
        ("a-op-t-1", "operator", "a-manager-b-1"),
        ("a-manager-b-2", "manager", "a-director"),
        ("a-op-t-2", "operator", "a-manager-b-2"),
        ("a-op-t-3", "operator", "a-manager-b-2"),
        ("a-auditor", "auditor", None),
    ]
    levels = [e.level for e in book.report(RUN_ID).entries]
    assert levels == [
        "director",
        "operator",
        "manager",
        "operator",
        "operator",
        "manager",
        "auditor",
    ]
    messages = [p.message for p in _payloads(team, "message")]
    assert [m.sender for m in messages] == ["director", "director"]
    assert messages[0].text.startswith("[stub] A plan.")
    finished = _payloads(team, "run_finished")[0]
    assert finished.spent_usd == book.report(RUN_ID).spent_usd and finished.partial is False
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_sub_budgets_follow_the_policy_and_unspent_money_goes_back():
    handler = TeamHandler(
        director=[plan_reply(block(2))],
        operator=[findings_reply(GOOD_CLAIM), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5")
    report = book.report(RUN_ID)
    nodes = {a.id: a for a in report.allocations}
    plan_cost = report.entries[0].usd_real  # 100 in, 20 out on Ultra
    assert plan_cost == D("0.000160")
    free_after_plan = D("0.5") - plan_cost
    assert nodes["budget:auditor"].usd == (free_after_plan * D("0.25")).quantize(
        D("0.000001"), "ROUND_FLOOR"
    )
    manager = nodes["budget:b-1"]
    assert manager.usd == free_after_plan - nodes["budget:auditor"].usd
    own = (manager.usd * D("0.30")).quantize(D("0.000001"), "ROUND_FLOOR")
    per_task = ((manager.usd - own) / 2).quantize(D("0.000001"), "ROUND_FLOOR")
    assert nodes["budget:t-1"].usd == per_task == nodes["budget:t-2"].usd
    assert nodes["budget:t-1"].parent == nodes["budget:t-2"].parent == "budget:b-1"
    assert team.blocks[0].released_usd == manager.usd - manager.spent_usd
    for task_id in ("t-1", "t-2"):
        task_v1 = next(
            p.task for p in _payloads(team, "task_assigned") if p.task.task_id == task_id
        )
        assert task_v1.budget.max_usd == per_task
    assert_budget_tree(book)


def test_the_director_running_out_of_budget_fails_the_run_cleanly():
    handler = TeamHandler()
    # The plan call's 256 output tokens alone cost USD 0.000768 on Ultra.
    team, book = run_stub_team(handler, run_usd="0.0002")
    assert team.status == "failed" and team.partial is False
    assert _types(team) == [
        "run_started",
        "agent_hired",
        "task_started",
        "attempt_recorded",
        "run_failed",
    ]
    failed = _payloads(team, "run_failed")[0]
    assert failed.error.code == "budget_exhausted" and failed.spent_usd == ZERO_USD
    details = failed.error.details
    assert (details["level"], details["scope"], details["key"], details["cap_usd"]) == (
        "director",
        "run",
        RUN_ID,
        "0.000200",
    )
    attempt = _payloads(team, "attempt_recorded")[0].attempt
    assert attempt.loop_status == "budget_exhausted" and attempt.model_calls == 0
    assert handler.bodies == [] and book.report(RUN_ID).entries == ()
    assert_contract_order(team, book)


def test_a_manager_running_out_of_budget_leaves_a_partial_block():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM)],
        auditor=[judgment_reply()],
    )
    # The manager's allocation is about USD 0.0224; its call's 8,192 output tokens alone
    # cost USD 0.0246. The operator and the auditor get many times what they need.
    team, book = run_stub_team(handler, run_usd="0.03")
    (outcome,) = team.blocks
    assert outcome.status == "partial" and outcome.summary is None
    assert outcome.tasks[0].status == "ok"
    assert "ran out of budget before its consolidation call" in outcome.reason
    assert handler.calls["manager"] == 0 and handler.calls["auditor"] == 1
    assert team.status == "finished" and team.partial is True
    assert team.notes == [outcome.reason]
    closing = [p.message.text for p in _payloads(team, "message")][-1]
    assert outcome.reason in closing
    assert _payloads(team, "run_finished")[0].partial is True
    stops = [(s.scope, s.key) for s in book.report(RUN_ID).stops]
    assert stops == [("budget", "budget:b-1")]
    manager_attempt = [
        p.attempt for p in _payloads(team, "attempt_recorded") if p.agent_id == "a-manager-b-1"
    ]
    assert [a.loop_status for a in manager_attempt] == ["budget_exhausted"]
    assert team.audit.verdict == "accepted"
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_an_operator_running_out_of_budget_fails_its_task_without_a_reassignment():
    handler = TeamHandler(director=[plan_reply(block(1))], auditor=[judgment_reply()])
    # The operator's allocation is USD 0.020916; on Ultra its 8,192 output tokens alone
    # cost USD 0.024576 (the task's output ceiling is raised so it does not cap them).
    # Its manager makes no call: no task was completed.
    expensive = [operator("stub-op-a", "0.001", model=ULTRA, max_tokens=8192)]
    policy = BudgetPolicy(operator_max_output_tokens=8192)
    team, book = run_stub_team(handler, run_usd="0.04", catalog=expensive, policy=policy)
    (task,) = team.blocks[0].tasks
    assert (task.status, task.assignments) == ("failed", ["t-1"])
    assert "ran out of its budget" in team.notes[0]
    (result,) = _payloads(team, "task_result")
    assert result.result.status == "failed" and result.label == "failed"
    assert "budget_exhausted" in result.result.self_check.notes
    assert len(_payloads(team, "task_assigned")) == 1  # a budget stop is not reassigned
    assert handler.calls["operator"] == 0 and handler.calls["manager"] == 0
    assert team.blocks[0].status == "failed" and team.partial is True
    assert ("budget", "budget:t-1") in [(s.scope, s.key) for s in book.report(RUN_ID).stops]
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_an_auditor_running_out_of_budget_accepts_with_a_warning():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
    )
    team, book = run_stub_team(
        handler, run_usd="0.5", policy=BudgetPolicy(auditor_share=D("0.0001"))
    )
    assert team.audit.verdict == "accepted_with_warning"
    assert "budget ran out" in team.audit.warning
    (check,) = team.audit.checks
    assert check.passed and "1 of 1 citations verified" in check.note
    assert handler.calls["auditor"] == 0
    assert team.partial is True and "auditor ran out of budget" in team.notes[-1]
    assert _payloads(team, "audit_result")[0].audit == team.audit
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_a_failed_operator_is_reassigned_to_the_next_catalog_operator():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(status="failed"), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5", harness_config=_no_ladder())
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and task.assignments == ["t-1", "t-1.2"]
    # The cheaper operator is tried first: selection is by catalog price, not list order.
    assert task.operator_ids == ["stub-op-a", "stub-op-b"]
    assigned = [(p.task.task_id, p.operator_id) for p in _payloads(team, "task_assigned")]
    assert assigned == [("t-1", "stub-op-a"), ("t-1.2", "stub-op-b")]
    labels = [(p.result.task_id, p.label) for p in _payloads(team, "task_result")]
    assert labels == [("t-1", "failed"), ("t-1.2", "first_pass_ok")]
    assert team.notes == [
        "t-1: operator stub-op-a failed (top_of_ladder); the manager reassigns the task."
    ]
    assert team.blocks[0].status == "ok" and team.partial is False
    nodes = {a.id: a for a in book.report(RUN_ID).allocations}
    assert nodes["budget:t-1"].closed and nodes["budget:t-1.2"].closed
    assert nodes["budget:t-1"].released_usd > 0  # the failed operator's unspent part
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_an_operator_failure_with_no_other_operator_escalates_to_the_director():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(status="failed")],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(
        handler,
        run_usd="0.5",
        catalog=[operator("stub-op-a", "0.001")],
        harness_config=_no_ladder(),
    )
    (outcome,) = team.blocks
    assert outcome.status == "failed" and outcome.tasks[0].status == "failed"
    assert team.notes == [
        "t-1: operator stub-op-a failed (top_of_ladder); escalated to the director.",
        "Block b-1 has no completed task; escalated to the director.",
    ]
    assert handler.calls["manager"] == 0  # nothing to consolidate
    assert team.partial is True and _payloads(team, "run_finished")[0].partial is True
    closing = [p.message.text for p in _payloads(team, "message")][-1]
    assert "Done: 0 of 1 tasks completed." in closing and "escalated to the director" in closing
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_the_auditor_rejects_an_unsupported_claim_without_a_model_call():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM, FABRICATED_CLAIM)],
        manager=[summary_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5")
    assert team.audit.verdict == "rejected"
    assert team.evidence.unsupported_claims == ["t-1:c2"]
    assert team.evidence.citation_verified_rate == 0.5
    (check,) = team.audit.checks
    assert not check.passed and "t-1:c2 (quote_not_found)" in check.note
    assert handler.calls["auditor"] == 0  # the deterministic check comes first
    assert [p.audit.verdict for p in _payloads(team, "audit_result")] == ["rejected"]
    assert not any(e.level == "auditor" for e in book.report(RUN_ID).entries)
    assert "Audit: rejected." in [p.message.text for p in _payloads(team, "message")][-1]
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_a_team_run_replays_from_a_cassette(tmp_path, monkeypatch):
    path = tmp_path / "team_run.json"

    def replies():
        return TeamHandler(
            director=[plan_reply(block(2))],
            operator=[findings_reply(GOOD_CLAIM), findings_reply(GOOD_CLAIM)],
            manager=[summary_reply()],
            auditor=[judgment_reply()],
        )

    recorded, recorded_book = run_stub_team(
        replies(), run_usd="0.5", cassette=Cassette(path, "record")
    )
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    replayed, replayed_book = run_stub_team(None, run_usd="0.5", cassette=Cassette(path, "replay"))
    assert replayed.audit == recorded.audit and replayed.notes == recorded.notes

    def comparable(team):  # a ledger entry's ts is the wall-clock time of its charge
        dumps = [e.model_dump() for e in team.events]
        for dump in dumps:
            if dump["type"] == "budget_update":
                dump["payload"]["entry"].pop("ts")
        return dumps

    assert comparable(replayed) == comparable(recorded)
    charges = [(e.task_id, e.usd_real) for e in replayed_book.report(RUN_ID).entries]
    assert charges == [(e.task_id, e.usd_real) for e in recorded_book.report(RUN_ID).entries]
    assert len(charges) == 5


def test_roles_are_data_in_the_skills_config():
    roles = load_team_roles()  # the repo's config/skills.json
    assert (roles.director.role, roles.manager.role, roles.auditor.role) == (
        "director",
        "manager",
        "auditor",
    )
    assert roles.auditor.skills == ("prose-style",)
    stub = load_team_roles(skills_config(manager_max_tokens=512))
    assert (stub.manager.role, stub.manager.model, stub.manager.max_tokens) == (
        "stub-manager",
        ULTRA,
        512,
    )
    missing = skills_config()
    del missing["roles"]["stub-auditor"]
    with pytest.raises(ValueError, match="auditor"):
        load_team_roles(missing)
    twice = skills_config()
    twice["roles"]["second-manager"] = dict(twice["roles"]["stub-manager"])
    with pytest.raises(ValueError, match="two roles"):
        load_team_roles(twice)
    unknown = skills_config()
    unknown["roles"]["stub-operator"]["level"] = "board"
    with pytest.raises(ValueError, match="level must be"):
        load_team_roles(unknown)


def test_the_budget_policy_takes_decimal_shares_only():
    with pytest.raises(TypeError, match="Decimal"):
        BudgetPolicy(auditor_share=0.25)
    with pytest.raises(ValueError):
        BudgetPolicy(manager_share=D("1.5"))
    assert BUNDLE.sources  # the stub bundle used above is not empty


def test_a_manager_with_nothing_for_its_operators_runs_no_task():
    handler = TeamHandler(director=[plan_reply(block(2))], auditor=[judgment_reply()])
    team, book = run_stub_team(handler, run_usd="0.5", policy=BudgetPolicy(manager_share=D("1")))
    (outcome,) = team.blocks
    assert [t.status for t in outcome.tasks] == ["not_run", "not_run"]
    assert team.notes[:2] == [
        "t-1: manager a-manager-b-1 has no budget left for it.",
        "t-2: manager a-manager-b-1 has no budget left for it.",
    ]
    assert outcome.status == "failed" and team.partial is True
    assert handler.calls["operator"] == 0 and handler.calls["manager"] == 0
    assert _payloads(team, "task_assigned") == []
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_a_plan_larger_than_the_policy_fails_the_run():
    handler = TeamHandler(director=[plan_reply(block(1), block(1))])
    team, book = run_stub_team(handler, run_usd="0.5", policy=BudgetPolicy(max_blocks=1))
    assert team.status == "failed" and _types(team)[-1] == "run_failed"
    failed = _payloads(team, "run_failed")[0]
    assert failed.error.code == "plan_too_large"
    assert failed.spent_usd == book.report(RUN_ID).spent_usd > 0  # the plan call was paid
    assert book.report(RUN_ID).allocations == ()
    assert_contract_order(team, book)
