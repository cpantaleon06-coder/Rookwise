"""First-pass citation validity before and after the operators' citation source is
derived from their slice. Stub transport; no network."""

from team_stub import (
    GOOD_CLAIM,
    RUN_ID,
    TeamHandler,
    block,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.benchmark import first_pass
from rookwise.evidence import EvidenceBundle
from rookwise.team.models import CitationCheck, CitationLog, SliceAssignment, findings_model

BUNDLE = EvidenceBundle(sources={"src-a": "the widget weighs 12 units.\nthe widget is blue.\n"})


def _store_ref(citation):
    return {**citation, "source_id": f"store://{RUN_ID}/slices/src-a:1-2"}


def test_a_derived_citation_counts_valid_after_and_invalid_before():
    log, assignment = CitationLog("t-1"), SliceAssignment()
    assignment.assign("t-1", "src-a", f"store://{RUN_ID}/slices/src-a:1-2")
    good = GOOD_CLAIM["citations"][0]
    claim = {**GOOD_CLAIM, "citations": [_store_ref(good), {**good, "line_start": 1}]}
    findings_model(BUNDLE, log, assignment).model_validate({"summary": "[stub]", "claims": [claim]})
    (reply,) = log.replies
    assert [c.ok for c in reply.citations] == [True, True]
    assert [c.ok_before_normalization for c in reply.citations] == [False, True]
    assert first_pass(log.replies) == (2, 2)
    assert first_pass(log.replies, before_normalization=True) == (1, 2)


def test_without_derivation_both_numbers_agree():
    check = CitationCheck(0, 0, False, "bad")
    assert check.ok_before_normalization is False
    assert CitationCheck(0, 0, True).ok_before_normalization is True


def test_the_team_score_carries_both_numbers():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[
            findings_reply({**GOOD_CLAIM, "citations": [_store_ref(GOOD_CLAIM["citations"][0])]})
        ],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    operator_replies = [r for r in team.citation_log if r.task_id == "t-1"]
    assert first_pass(operator_replies) == (1, 1)
    assert first_pass(operator_replies, before_normalization=True) == (0, 1)
