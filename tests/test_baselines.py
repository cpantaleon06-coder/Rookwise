"""The single-model baselines (b) and (c): one model reads every slice with the operators'
prompt and findings model, then writes the diagnosis; the deterministic check and D3 are
the whole verification. Stub transport; no network."""

import dataclasses

from team_stub import (
    FABRICATED_CLAIM,
    GOOD_CLAIM,
    LIGHTNING,
    RUN_ID,
    TeamHandler,
    assert_contract_order,
    diagnosis_reply,
    findings_reply,
    operator,
    run_stub_team,
)

from rookwise.benchmark import first_pass
from rookwise.evidence import EvidenceBundle
from rookwise.harness import load_config
from rookwise.team import BudgetPolicy
from rookwise.team.flow import Baseline

ULTRA = "nemotron-3-ultra"
# SYNTHETIC: two sources, one slice each at the stub's slice size.
BUNDLE = EvidenceBundle(
    sources={
        "src-a": "Sample record one: the widget weighs 12 units.\n"
        "Sample record two: the widget is blue.\n",
        "notes.md": "# SYNTHETIC notes\nNothing else happened.\n",
    }
)


def _run(model, diagnosis, operators=None):
    handler = TeamHandler(
        operator=operators or [findings_reply(GOOD_CLAIM), findings_reply()],
        diagnosis=diagnosis,
    )  # no director plan, manager or auditor reply: any such call fails the handler
    baseline = Baseline(model=model, instruction="[stub] Read it.", default_role="stub-operator")
    config = load_config(env={})
    no_ladder = dataclasses.replace(
        config, escalation=dataclasses.replace(config.escalation, next={})
    )
    team, book = run_stub_team(
        handler,
        run_usd="1.0",
        bundle=BUNDLE,
        catalog=[operator("stub-baseline", "0.001", model=model)],
        harness_config=no_ladder,
        policy=BudgetPolicy(max_reassignments=0, task_limit_next_rung_reservations=0),
        baseline=baseline,
    )
    return team, book, handler


def test_one_model_reads_every_slice_then_writes_the_diagnosis():
    team, book, handler = _run(LIGHTNING, [diagnosis_reply(GOOD_CLAIM)])
    assert handler.calls == {
        "director": 0,
        "diagnosis": 1,
        "manager": 0,
        "auditor": 0,
        "operator": 2,
    }
    (block,) = team.blocks
    assert block.slices_read == 2 and not team.unread_slices
    assert {b["model"] for b in handler.bodies} == {load_config(env={}).model(LIGHTNING).model_id}
    hired = [e.payload.agent for e in team.events if e.type == "agent_hired"]
    assert [a.level for a in hired] == ["director", "operator", "operator"]
    assert all(a.parent_id == "a-director" for a in hired[1:])  # no manager in between
    assert team.diagnosis_status == "audited" and team.supported_claims
    assert team.audit.verdict == "accepted_with_warning" and team.audit.model == "none"
    assert "only the deterministic check ran" in team.audit.warning
    assert_contract_order(team, book)
    # One pool, drawn from the run, opened before the operators and closed after them.
    report = book.report(RUN_ID)
    (pool,) = report.allocations
    assert pool.id == "pool:baseline" and pool.parent is None and pool.closed
    assert report.held_usd == 0 and report.spent_usd <= report.caps.run_usd


def test_the_baseline_on_ultra_uses_ultra_for_every_call():
    team, _, handler = _run(ULTRA, [diagnosis_reply(GOOD_CLAIM)])
    assert {b["model"] for b in handler.bodies} == {load_config(env={}).model(ULTRA).model_id}
    assert {e.model for e in team.report.entries} == {ULTRA}


def test_an_unsupported_claim_of_the_baseline_is_withdrawn_by_d3():
    team, _, handler = _run(
        LIGHTNING, [diagnosis_reply(GOOD_CLAIM, FABRICATED_CLAIM, root=("c1",))]
    )
    assert [w.claim.claim_id for w in team.withdrawn_claims] == ["c2"]
    assert [c.claim_id for c in team.supported_claims] == ["c1"]
    assert "1 claims were withdrawn" in team.audit.warning


def test_the_baseline_reports_both_first_pass_numbers():
    ref = {**GOOD_CLAIM["citations"][0], "source_id": f"store://{RUN_ID}/slices/src-a:1-2"}
    team, _, _ = _run(
        LIGHTNING,
        [diagnosis_reply(GOOD_CLAIM)],
        operators=[findings_reply({**GOOD_CLAIM, "citations": [ref]}), findings_reply()],
    )
    operators = [r for r in team.citation_log if r.task_id.startswith("t-")]
    assert first_pass(operators) == (1, 1)
    assert first_pass(operators, before_normalization=True) == (0, 1)
    assert team.citation_source_normalizations == {"t-1": 1}
