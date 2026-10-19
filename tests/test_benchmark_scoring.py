"""Diagnosis scoring (core/benchmark.py) on stub outputs and a synthetic ground truth.
No network, no gitignored logs."""

import json

from harness_support import text_reply
from team_stub import (
    BUNDLE,
    GOOD_CLAIM,
    TeamHandler,
    block,
    diagnosis_payload,
    findings_payload,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.benchmark import citation_repairs, first_pass, score_diagnosis, score_run
from rookwise.incidents import GroundTruth
from rookwise.team.models import CitationCheck, Diagnosis, ReplyCitations

ESSENTIAL = {
    "source_id": "src-a",
    "line_start": 1,
    "line_end": 1,
    "quote": "the widget weighs 12 units.",
    "note": "[stub] the cause",
}
DECOY = {
    "source_id": "src-a",
    "line_start": 2,
    "line_end": 2,
    "quote": "the widget is blue.",
    "note": "[stub] unrelated",
}
TRUTH = GroundTruth.model_validate(
    {
        "synthetic": True,
        "note": "SYNTHETIC test ground truth",
        "incident_id": "inc-test",
        "split": "dev",
        "difficulty": "easy",
        "root_cause": "[stub] The widget is too heavy.",
        "root_cause_category": "bad_config",
        "categories": ["bad_config"],
        "essential_evidence": [ESSENTIAL],
        "supporting_evidence": [],
        "decoys": [DECOY, DECOY],
        "acceptable_remediations": ["[stub] Lighten the widget."],
        "keyword_free_evidence": False,
        "cause_in_deploy_diff": False,
        "misleading_first_hypothesis": None,
        "sources": {"src-a": {"lines": 2, "committed": True}},
        "log_lines": 0,
        "seed": 0,
    }
)
BAD_CITATION = {"source_id": "src-a", "line_start": 2, "line_end": 2, "quote": "purple"}


def _diagnosis(*claims, root=None, category="bad_config"):
    output = json.loads(diagnosis_payload(*claims, root=root, category=category))["output"]
    return Diagnosis.model_validate(output)


def test_the_right_category_with_a_verified_essential_citation_is_correct():
    result = score_diagnosis(_diagnosis(GOOD_CLAIM), TRUTH, bundle=BUNDLE)
    assert result.diagnosis_correct and result.score.category_correct
    assert result.score.evidence_recall == 1.0 and result.withdrawn_claims == 0


def test_the_right_category_whose_only_essential_citation_was_withdrawn_is_not_correct():
    # The claim cites the essential line, but a second citation fails, so D3 withdraws the
    # whole claim and its essential citation counts for nothing.
    claim = json.loads(json.dumps(GOOD_CLAIM))
    claim["citations"].append(BAD_CITATION)
    result = score_diagnosis(_diagnosis(claim), TRUTH, bundle=BUNDLE)
    assert result.score.category_correct and not result.diagnosis_correct
    assert result.score.evidence_recall == 0.0 and result.withdrawn_claims == 1
    assert result.score.evidence.citations_total == 0  # only supported claims are scored


def test_the_wrong_category_or_no_diagnosis_is_not_correct():
    wrong = score_diagnosis(
        _diagnosis(GOOD_CLAIM, category="disk_exhaustion"), TRUTH, bundle=BUNDLE
    )
    assert not wrong.diagnosis_correct and wrong.score.evidence_recall == 1.0
    missing = score_diagnosis(None, TRUTH, bundle=BUNDLE)
    assert not missing.diagnosis_correct and missing.score.category is None


def test_first_pass_validity_counts_first_replies_only():
    log = [
        ReplyCitations("t-1", 0, (CitationCheck(0, 0, True), CitationCheck(0, 1, False, "x"))),
        ReplyCitations("t-1", 1, (CitationCheck(0, 0, True), CitationCheck(0, 1, True))),
        ReplyCitations("diagnosis", 0, (CitationCheck(0, 0, True),)),
    ]
    assert first_pass(log) == (2, 3)
    result = score_diagnosis(_diagnosis(GOOD_CLAIM), TRUTH, bundle=BUNDLE, citation_log=log)
    assert (result.first_pass_valid, result.first_pass_citations) == (2, 3)
    assert abs(result.citation_first_pass_validity - 2 / 3) < 1e-12
    assert score_diagnosis(None, TRUTH, bundle=BUNDLE).citation_first_pass_validity is None


def test_a_team_run_reports_per_citation_results_and_its_citation_repairs():
    two = json.loads(json.dumps(GOOD_CLAIM))
    two["citations"].append(BAD_CITATION)  # fails the run-bound check: a citation error
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[text_reply(findings_payload(two)), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    by_task = {(r.task_id, r.index): r for r in team.citation_log}
    first = by_task[("t-1", 0)]
    assert [c.ok for c in first.citations] == [True, False]
    assert "is not part of one line" in first.citations[1].problem
    assert [c.ok for c in by_task[("t-1", 1)].citations] == [True]
    assert [c.ok for c in by_task[("diagnosis", 0)].citations] == [True]
    result = score_run(team, TRUTH, bundle=BUNDLE)
    assert result.diagnosis_correct
    assert (result.first_pass_valid, result.first_pass_citations) == (2, 3)
    assert result.citation_repairs == 1
    attempts = [e.payload.attempt for e in team.events if e.type == "attempt_recorded"]
    assert citation_repairs(attempts) == 1


def test_a_repair_for_another_error_is_not_a_citation_repair():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[
            text_reply('{"status": "ok", "output": {"claims": []}}'),
            findings_reply(GOOD_CLAIM),
        ],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    attempts = [e.payload.attempt for e in team.events if e.type == "attempt_recorded"]
    assert [a.reason for a in attempts if a.task_id == "t-1"] == ["first", "repair"]
    assert citation_repairs(attempts) == 0
