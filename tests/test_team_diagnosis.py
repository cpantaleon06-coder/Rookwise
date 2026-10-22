"""The director's diagnosis: schema, run-bound validation and what the director receives.
Stub transport and synthetic data only; no network."""

import json
import typing

import pytest
from harness_support import text_reply
from team_stub import (
    BUNDLE,
    GOOD_CLAIM,
    RUN_ID,
    TeamHandler,
    block,
    diagnosis_payload,
    diagnosis_reply,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.evidence import EvidenceBundle
from rookwise.harness.validate import final_result_instructions, payload_model, validate_final
from rookwise.incidents import CATEGORIES, Category
from rookwise.team.models import CitationLog, Diagnosis, RemediationStep, diagnosis_model

STEP = {"action": "[stub] a", "why": "[stub] b", "risk": "[stub] c", "reversible": False}
OTHER = EvidenceBundle(
    sources={"ticket.md": "# SYNTHETIC\nThe widget alarm fired.\n", **BUNDLE.sources}
)


def _output(**overrides):
    output = json.loads(diagnosis_payload())["output"]
    return output | overrides


def test_the_schema_is_the_same_for_the_plain_and_the_run_bound_model():
    bound = diagnosis_model(BUNDLE)
    assert bound.__name__ == "Diagnosis"
    assert final_result_instructions(bound) == final_result_instructions(Diagnosis)


def test_the_category_reuses_the_benchmark_enum_and_the_plan_steps_are_complete():
    assert typing.get_args(Category) == CATEGORIES and len(CATEGORIES) == 8
    schema = payload_model(Diagnosis).model_json_schema()["$defs"]
    assert schema["Diagnosis"]["properties"]["category"]["enum"] == list(CATEGORIES)
    assert set(schema["RemediationStep"]["required"]) == {"action", "why", "risk", "reversible"}
    RemediationStep.model_validate(STEP)
    with pytest.raises(ValueError):
        RemediationStep.model_validate(STEP | {"reversible": None})


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"category": "cosmic_rays"}, "category"),
        ({"root_cause_claim_ids": ["c9"]}, "c9 are not claim ids"),
        ({"root_cause_claim_ids": []}, "root_cause_claim_ids"),
        ({"remediation_plan": []}, "remediation_plan"),
        ({"claims": [GOOD_CLAIM, GOOD_CLAIM]}, "claim ids must be unique"),
    ],
)
def test_an_invalid_diagnosis_fails_validation(overrides, expected):
    validation = validate_final({"status": "ok", "output": _output(**overrides)}, Diagnosis)
    assert not validation.ok and any(expected in e for e in validation.errors)


def test_the_run_model_checks_shape_only_and_logs_every_citation():
    bad = json.loads(json.dumps(GOOD_CLAIM))
    bad["citations"][0]["quote"] = "the widget weighs 13 units."
    output = _output(claims=[GOOD_CLAIM, bad | {"claim_id": "c2"}])
    log = CitationLog("diagnosis")
    run_model = diagnosis_model(BUNDLE, log)
    assert validate_final({"status": "ok", "output": output}, run_model).ok  # not rejected
    (reply,) = log.replies
    assert [c.ok for c in reply.citations] == [True, False]
    assert "is not part of one line" in reply.citations[1].problem
    # Shape still counts: a multi-line quote, an unknown category, a bad root id.
    multi = json.loads(json.dumps(GOOD_CLAIM))
    multi["citations"][0]["quote"] = "a\nb"
    for broken in (
        _output(claims=[multi]),
        _output(category="x"),
        _output(root_cause_claim_ids=["c9"]),
    ):
        assert not validate_final({"status": "ok", "output": broken}, run_model).ok


BOTH = plan_reply(block(1), block(1, source_id="ticket.md"))


def _team(context_sources=(), **replies):
    replies.setdefault("director", [BOTH])
    replies.setdefault("operator", [findings_reply(GOOD_CLAIM), findings_reply(GOOD_CLAIM)])
    replies.setdefault("manager", [summary_reply(), summary_reply()])
    replies.setdefault("auditor", [judgment_reply()])
    handler = TeamHandler(**replies)
    team, book = run_stub_team(
        handler, run_usd="0.5", bundle=OTHER, context_sources=context_sources
    )
    return team, book, handler


def test_the_director_receives_context_inventory_and_findings_by_reference():
    plan = plan_reply(
        {
            "goal": "[stub] Read both.",
            "tasks": [
                {"role": "stub-operator", "source_id": "src-a", "instruction": "[stub] Read."},
                {"role": "stub-operator", "source_id": "ticket.md", "instruction": "[stub] Read."},
            ],
        }
    )
    # Each operator cites its own slice: the ticket's operator reports no claim.
    team, _, handler = _team(
        context_sources=("ticket.md",),
        director=[plan],
        operator=[findings_reply(GOOD_CLAIM), findings_reply()],
    )
    (body,) = [
        b
        for b in handler.bodies
        if b["messages"][0]["content"].startswith(
            "You are the director of a team of AI agents, and"
        )
    ]
    user = body["messages"][-1]["content"]
    assert "Source ticket.md (cite it by this id and these line numbers):\n1: # SYNTHETIC" in user
    assert "- src-a: 2 lines, 1 slices" in user and "- ticket.md: 2 lines, 1 slices" in user
    assert f"[store://{RUN_ID}/summaries/b-1]" in user
    assert f"[store://{RUN_ID}/results/t-1] t-1 (stub-operator, src-a:1-2):" in user
    assert "the widget weighs 12 units." in user  # the operators' citations come along
    assert team.diagnosis is not None and team.diagnosis.category == "bad_config"
    assert team.diagnosis.root_cause_claim_ids == ["c1"]
    entries = [e for e in team.report.entries if e.task_id == "diagnosis"]
    assert [e.level for e in entries] == ["director"]


def _bad(claim_id="c1", quote="the widget weighs 13 units."):
    claim = json.loads(json.dumps(GOOD_CLAIM))
    claim["claim_id"] = claim_id
    claim["citations"][0]["quote"] = quote
    return claim


def test_one_bad_quote_among_good_claims_is_withdrawn_and_the_rest_audited():
    team, _, handler = _team(diagnosis=[diagnosis_reply(GOOD_CLAIM, _bad("c2"), root=("c1",))])
    assert handler.calls["diagnosis"] == 1 and team.diagnosis_repairs == 0
    assert team.diagnosis_status == "audited" and handler.calls["auditor"] == 1
    assert [(w.claim.claim_id, w.reason) for w in team.withdrawn_claims] == [
        ("c2", "quote_not_found")
    ]
    assert team.claim_counts.by_reason == {"quote_not_found": 1}
    (first,) = [r for r in team.citation_log if r.task_id == "diagnosis"]
    assert [c.ok for c in first.citations] == [True, False]


def test_all_root_claims_bad_gets_one_targeted_repair_then_is_audited():
    team, _, handler = _team(diagnosis=[diagnosis_reply(_bad()), diagnosis_reply()])
    assert handler.calls["diagnosis"] == 2 and team.diagnosis_repairs == 1
    (request,) = [
        b["messages"][-1]["content"]
        for b in handler.bodies
        if "withdrew every claim" in b["messages"][-1]["content"]
    ]
    assert "withdrew every claim your root cause rests on" in request
    assert "- c1: quote_not_found. citation 0: quote_not_found" in request
    assert "1: Sample record one: the widget weighs 12 units." in request
    assert team.first_diagnosis.claims[0].citations[0].quote.endswith("13 units.")
    assert team.diagnosis_status == "audited" and team.withdrawn_claims == []
    replies = [r for r in team.citation_log if r.task_id == "diagnosis"]
    assert [(r.index, [c.ok for c in r.citations]) for r in replies] == [(0, [False]), (1, [True])]
    ids = [e.task_id for e in team.report.entries if e.level == "director"]
    assert ids == ["plan", "diagnosis", "diagnosis-repair"]


def test_all_root_claims_still_bad_after_the_repair_is_inconclusive():
    team, _, handler = _team(
        diagnosis=[diagnosis_reply(_bad()), diagnosis_reply(_bad())], auditor=[]
    )
    assert handler.calls["diagnosis"] == 2 and team.diagnosis_repairs == 1  # only one repair
    assert team.diagnosis_status == "inconclusive" and handler.calls["auditor"] == 0
    assert team.inconclusive_reason == "no supported claim remains"  # its only claim


def test_no_valid_diagnosis_is_a_note_not_a_crash():
    junk = text_reply('{"status": "ok", "output": {"root_cause": "x"}}')
    team, _, _ = _team(diagnosis=[junk, junk, junk, junk, junk, junk, junk, junk, junk])
    assert team.diagnosis is None
    assert any("no valid diagnosis" in note for note in team.notes)


def test_unknown_context_sources_are_refused():
    with pytest.raises(ValueError, match="context sources"):
        _team(context_sources=("missing.md",))
