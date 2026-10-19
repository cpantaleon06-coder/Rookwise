"""The team hierarchy (core/team) on scripted stubs and a cassette. No network.

Budgets are chosen so the case under test does not depend on the size of a prompt: a
level that must run out of budget gets less than its output tokens alone would cost
(every team agent is on Ultra, USD 3 per 1M output tokens), and the other levels get
several times what they need.
"""

import dataclasses
from decimal import Decimal

import pytest
from harness_support import text_reply
from team_stub import (
    BUNDLE,
    FABRICATED_CLAIM,
    GOOD_CLAIM,
    LIGHTNING,
    RUN_ID,
    ULTRA,
    UNCITED_CLAIM,
    TeamHandler,
    assert_budget_tree,
    assert_contract_order,
    block,
    diagnosis_reply,
    findings_payload,
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


def _allocations(team):
    return [(p.action, p.agent_id, p.parent_agent_id) for p in _payloads(team, "budget_allocation")]


def _escalations(team):
    return [(p.from_agent_id, p.to_agent_id, p.task_id) for p in _payloads(team, "escalation")]


def _stops(team):
    return [(p.agent_id, p.level, p.scope, p.key) for p in _payloads(team, "budget_exhausted")]


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
    assert team.operator_evidence.citations_total == 3  # the operators' claims
    assert team.evidence.citations_total == 1  # the diagnosis's claims
    assert team.diagnosis_status == "audited" and team.withdrawn_claims == []
    assert handler.calls == {
        "director": 1,
        "diagnosis": 1,
        "manager": 2,
        "auditor": 1,
        "operator": 3,
    }
    hired = [p.agent for p in _payloads(team, "agent_hired")]
    # The auditor and the managers are hired with their allocations, right after the plan.
    assert [(a.agent_id, a.level, a.parent_id) for a in hired] == [
        ("a-director", "director", None),
        ("a-auditor", "auditor", None),
        ("a-manager-b-1", "manager", "a-director"),
        ("a-manager-b-2", "manager", "a-director"),
        ("a-op-t-1", "operator", "a-manager-b-1"),
        ("a-op-t-2", "operator", "a-manager-b-2"),
        ("a-op-t-3", "operator", "a-manager-b-2"),
    ]
    assert _allocations(team) == [
        ("allocated", "a-auditor", "a-director"),
        ("allocated", "a-manager-b-1", "a-director"),
        ("allocated", "a-manager-b-2", "a-director"),
        ("allocated", "a-op-t-1", "a-manager-b-1"),
        ("released", "a-op-t-1", "a-manager-b-1"),
        ("released", "a-manager-b-1", "a-director"),
        ("allocated", "a-op-t-2", "a-manager-b-2"),
        ("released", "a-op-t-2", "a-manager-b-2"),
        ("allocated", "a-op-t-3", "a-manager-b-2"),
        ("released", "a-op-t-3", "a-manager-b-2"),
        ("released", "a-manager-b-2", "a-director"),
        ("released", "a-auditor", "a-director"),
    ]
    assert _escalations(team) == [] and _stops(team) == []
    levels = [e.level for e in book.report(RUN_ID).entries]
    assert levels == [
        "director",
        "operator",
        "manager",
        "operator",
        "operator",
        "manager",
        "director",  # the diagnosis
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
    events = {(p.action, p.agent_id): p for p in _payloads(team, "budget_allocation")}
    auditor = events[("allocated", "a-auditor")]
    assert auditor.usd == nodes["budget:auditor"].usd
    assert auditor.parent_free_usd == free_after_plan - auditor.usd
    assert events[("allocated", "a-manager-b-1")].parent_free_usd == ZERO_USD  # all split
    first_operator = events[("allocated", "a-op-t-1")]
    assert first_operator.usd == per_task
    assert first_operator.parent_free_usd == manager.usd - per_task  # nothing spent in it yet
    released = events[("released", "a-manager-b-1")]
    assert released.usd == team.blocks[0].released_usd
    last = _payloads(team, "budget_allocation")[-1]  # the auditor's, once everything is closed
    assert (last.action, last.agent_id) == ("released", "a-auditor")
    assert last.parent_free_usd + report.spent_usd == D("0.5")
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
        "budget_exhausted",
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
    (stop,) = _payloads(team, "budget_exhausted")
    assert (stop.agent_id, stop.level, stop.scope, stop.key) == (
        "a-director",
        "director",
        "run",
        RUN_ID,
    )
    assert (stop.cap_usd, stop.committed_usd) == (D("0.0002"), ZERO_USD)
    assert stop.requested_usd > stop.cap_usd and details["requested_usd"] == f"{stop.requested_usd}"
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
    assert _stops(team) == [("a-manager-b-1", "manager", "budget", "budget:b-1")]
    assert _escalations(team) == []  # a budget stop is not an escalation
    types = _types(team)
    stopped = types.index("budget_exhausted")
    assert types[stopped - 1] == "attempt_recorded"  # the manager's refused call
    assert _allocations(team)[-2] == ("released", "a-manager-b-1", "a-director")
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
    expensive = [operator("stub-op-a", "0.001", model=ULTRA)]
    policy = BudgetPolicy(operator_max_output_tokens=8192)
    config = skills_config(operator_max_tokens=8192)
    team, book = run_stub_team(
        handler, run_usd="0.04", catalog=expensive, policy=policy, config=config
    )
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
    assert _stops(team) == [("a-op-t-1", "operator", "budget", "budget:t-1")]
    types = _types(team)
    assert types.index("budget_exhausted") == types.index("task_result") - 1
    # No reassignment; the block has no completed task, so the manager escalates it whole.
    assert _escalations(team) == [("a-manager-b-1", "a-director", None)]
    assert _payloads(team, "escalation")[0].reason == team.notes[-1]
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
    assert _stops(team) == [("a-auditor", "auditor", "budget", "budget:auditor")]
    types = _types(team)
    assert types.index("budget_exhausted") == types.index("audit_result") - 1
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
    assert _escalations(team) == [("a-op-t-1", "a-op-t-1.2", "t-1")]
    assert _payloads(team, "escalation")[0].reason == team.notes[0]
    # task_result and release of the first operator, hire of the next, the escalation
    # between them, the next allocation, then the new assignment.
    start = next(i for i, e in enumerate(team.events) if e.type == "task_result")
    assert [(e.type, getattr(e.payload, "agent_id", None)) for e in team.events[start:]][:6] == [
        ("task_result", "a-op-t-1"),
        ("budget_allocation", "a-op-t-1"),
        ("agent_hired", None),
        ("escalation", None),
        ("budget_allocation", "a-op-t-1.2"),
        ("task_assigned", "a-op-t-1.2"),
    ]
    assert _stops(team) == []
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
    assert _escalations(team) == [
        ("a-manager-b-1", "a-director", "t-1"),
        ("a-manager-b-1", "a-director", None),
    ]
    assert [p.reason for p in _payloads(team, "escalation")] == team.notes
    assert_contract_order(team, book)
    assert_budget_tree(book)


def _cut_reply() -> bytes:
    """An operator reply cut at its output ceiling (finish_reason length)."""
    return text_reply(
        '{"status": "ok", "output": {"summary": "[stub] cut', completion=256, reason="length"
    )


def test_a_length_finish_is_a_task_ceiling_with_one_reassignment():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[_cut_reply(), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5")
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and task.assignments == ["t-1", "t-1.2"]
    assert task.operator_ids == ["stub-op-a", "stub-op-b"]
    assert team.notes == [
        "t-1: operator stub-op-a failed (length): it hit its task ceiling; the manager "
        "reassigns the task."
    ]
    first = next(
        p.attempt for p in _payloads(team, "attempt_recorded") if p.attempt.task_id == "t-1"
    )
    assert (first.loop_status, first.model, first.length_retries) == ("length", LIGHTNING, 0)
    assert handler.calls["operator"] == 2  # the cut reply was not retried
    assert _escalations(team) == [("a-op-t-1", "a-op-t-1.2", "t-1")]
    assert _stops(team) == []  # a task ceiling is not a ledger stop
    assert team.partial is False
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_a_task_ceiling_gets_at_most_one_reassignment():
    catalog = [operator(f"stub-op-{c}", f"0.00{n}") for n, c in enumerate("abc", 1)]
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[_cut_reply(), _cut_reply()],
        auditor=[judgment_reply()],
    )
    policy = BudgetPolicy(max_reassignments=2)
    team, book = run_stub_team(handler, run_usd="0.5", catalog=catalog, policy=policy)
    (task,) = team.blocks[0].tasks
    assert task.status == "failed" and task.assignments == ["t-1", "t-1.2"]
    assert handler.calls["operator"] == 2  # stub-op-c is never tried
    assert team.notes[1] == (
        "t-1.2: operator stub-op-b failed (length): it hit its task ceiling; escalated to "
        "the director."
    )
    assert _escalations(team)[1] == ("a-manager-b-1", "a-director", "t-1.2")
    assert _stops(team) == []
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_a_task_ceiling_with_no_other_operator_moves_one_rung_up_the_ladder():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[_cut_reply(), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5", catalog=[operator("stub-op-a", "0.001")])
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and task.operator_ids == ["stub-op-a", "stub-op-a"]
    hired = {p.agent.agent_id: p.agent.model for p in _payloads(team, "agent_hired")}
    assert (hired["a-op-t-1"], hired["a-op-t-1.2"]) == (LIGHTNING, "nemotron-3-super")
    models = [e.model for e in book.report(RUN_ID).entries if e.level == "operator"]
    assert models == [LIGHTNING, "nemotron-3-super"]
    assert_contract_order(team, book)


def test_a_token_ceiling_is_a_task_ceiling_too():
    # The first reply fails validation and spends the task's whole output budget, so the
    # repair is not sent (token_ceiling); the next operator gets a fresh budget.
    bad = text_reply('{"status": "ok", "output": {}}', completion=10)
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[bad, text_reply(findings_payload(GOOD_CLAIM), completion=10)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    policy = BudgetPolicy(operator_max_output_tokens=10)
    team, book = run_stub_team(handler, run_usd="0.5", policy=policy)
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and task.assignments == ["t-1", "t-1.2"]
    assert "failed (token_ceiling): it hit its task ceiling" in team.notes[0]
    assert _stops(team) == []
    assert_contract_order(team, book)


def test_a_fabricated_quote_fails_the_operators_validation_and_is_repaired():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM, FABRICATED_CLAIM), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    first = next(
        p.attempt for p in _payloads(team, "attempt_recorded") if p.attempt.task_id == "t-1"
    )
    assert first.reason == "first" and not first.ok
    assert any("is not part of one line" in e for e in first.validation_errors)
    # Only the repaired reply reached the audit.
    assert team.evidence.citations_total == 1 and team.evidence.all_supported
    assert team.audit.verdict == "accepted"


def test_an_inconclusive_diagnosis_gets_no_auditor_model_call():
    # A claim with no citation passes the schema; the evidence check rejects it, and when
    # it is the only root-cause claim the diagnosis is inconclusive (D3).
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        diagnosis=[diagnosis_reply(GOOD_CLAIM, UNCITED_CLAIM, root=("c2",))],
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5")
    assert team.diagnosis_status == "inconclusive"
    assert team.inconclusive_reason == "every root-cause claim was withdrawn"
    assert [w.claim.claim_id for w in team.withdrawn_claims] == ["c2"]
    assert team.audit.verdict == "rejected" and "Inconclusive" in team.audit.warning
    check, conclusive = team.audit.checks
    assert not check.passed and "c2 (no_citations)" in check.note
    assert not conclusive.passed and conclusive.note == team.inconclusive_reason
    assert handler.calls["auditor"] == 0  # the deterministic check comes first
    assert [p.audit.verdict for p in _payloads(team, "audit_result")] == ["rejected"]
    assert not any(e.level == "auditor" for e in book.report(RUN_ID).entries)
    closing = [p.message.text for p in _payloads(team, "message")][-1]
    assert "Diagnosis: inconclusive" in closing and "Withdrawn: c2 (no_citations)." in closing
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
    assert len(charges) == 6


def test_roles_are_data_in_the_skills_config():
    roles = load_team_roles()  # the repo's config/skills.json
    assert (roles.director.role, roles.manager.role, roles.auditor.role) == (
        "director",
        "manager",
        "auditor",
    )
    assert roles.auditor.skills == ("prose-style",)
    stub = load_team_roles(skills_config(manager_max_tokens=512))
    assert (stub.manager.role, stub.manager.model, stub.manager.max_output_tokens) == (
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
    assert ("allocated", "a-op-t-1", "a-manager-b-1") not in _allocations(team)
    assert _escalations(team) == [("a-manager-b-1", "a-director", None)]
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
    assert _allocations(team) == [] and "agent_hired" not in _types(team)[2:]
    assert_contract_order(team, book)


def test_a_manager_that_cannot_consolidate_escalates_its_call_to_the_director():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply(status="failed")],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5", harness_config=_no_ladder())
    (outcome,) = team.blocks
    assert outcome.status == "partial" and outcome.summary is None
    assert team.notes == [
        "Manager b-1 could not consolidate (top_of_ladder); escalated to the director."
    ]
    assert _escalations(team) == [("a-manager-b-1", "a-director", "b-1-summary")]
    assert _payloads(team, "escalation")[0].reason == team.notes[0]
    assert _stops(team) == [] and team.partial is True
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_a_plan_call_charged_over_the_run_cap_fails_before_any_allocation():
    # The reservation fits the cap; the reported usage (50,000 input tokens on Ultra,
    # USD 0.05) does not, so the charge stops the run and nothing can be allocated.
    handler = TeamHandler(director=[plan_reply(block(1), prompt=50_000)])
    team, book = run_stub_team(handler, run_usd="0.01")
    assert team.status == "failed"
    assert team.notes == ["The run budget was used up by the director's plan call."]
    (stop,) = _payloads(team, "budget_exhausted")
    assert (stop.agent_id, stop.scope, stop.key, stop.cap_usd) == (
        "a-director",
        "run",
        RUN_ID,
        D("0.01"),
    )
    assert stop.committed_usd == book.report(RUN_ID).spent_usd > stop.cap_usd
    assert stop.requested_usd == ZERO_USD  # the stop came from a charge, not a reservation
    assert _types(team)[-2:] == ["budget_exhausted", "run_failed"]
    assert _allocations(team) == [] and book.report(RUN_ID).allocations == ()
    assert [p.agent.agent_id for p in _payloads(team, "agent_hired")] == ["a-director"]
    assert_contract_order(team, book)
