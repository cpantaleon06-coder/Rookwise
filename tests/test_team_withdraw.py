"""Decision D3: unsupported claims of the diagnosis are withdrawn (never dropped) before
the audit, and the auditor model reviews the supported rest. Stub data; no network."""

import json

from harness_support import text_reply
from team_stub import (
    BUNDLE,
    GOOD_CLAIM,
    UNCITED_CLAIM,
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

from rookwise.team.auditor import AUDIT_RUBRIC, split_claims
from rookwise.team.models import Diagnosis


def _citation(quote, line=1, source_id="src-a"):
    return {"source_id": source_id, "line_start": line, "line_end": line, "quote": quote}


def _claim(claim_id, *citations):
    return {"claim_id": claim_id, "text": f"[stub] {claim_id}", "citations": list(citations)}


def test_split_claims_withdraws_every_unsupported_claim_with_its_reasons():
    claims = [
        _claim("ok", _citation("the widget weighs 12 units.")),
        _claim("fake", _citation("the widget weighs 15 units.")),
        _claim("ghost", _citation("anything", source_id="nope")),
        _claim("far", _citation("the widget is blue.", line=9)),
        _claim("bare"),
        _claim("mixed", _citation("the widget is blue.", line=2), _citation("purple", line=2)),
    ]
    output = json.loads(diagnosis_payload(*claims, root=("ok",)))["output"]
    diagnosis = Diagnosis.model_validate(output)  # plain model: bad quotes get through
    split = split_claims(diagnosis, BUNDLE)
    assert [c.claim_id for c in split.supported] == ["ok"]
    withdrawn = {w.claim.claim_id: w for w in split.withdrawn}
    assert list(withdrawn) == ["fake", "ghost", "far", "bare", "mixed"]  # order kept
    assert len(split.supported) + len(split.withdrawn) == len(claims)  # nothing dropped
    assert {k: w.reason for k, w in withdrawn.items()} == {
        "fake": "quote_not_found",
        "ghost": "source_missing",
        "far": "line_out_of_range",
        "bare": "no_citations",
        "mixed": "quote_not_found",
    }
    assert withdrawn["mixed"].citation_reasons == ("ok", "quote_not_found")
    counts = split.counts
    assert (counts.supported, counts.withdrawn) == (1, 5)
    assert counts.by_reason == {
        "line_out_of_range": 1,
        "no_citations": 1,
        "quote_not_found": 2,
        "source_missing": 1,
    }


def _run(diagnosis, auditor=None):
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        diagnosis=diagnosis,
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=auditor if auditor is not None else [judgment_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5")
    return team, handler


def test_withdrawn_claims_are_listed_and_the_auditor_reviews_the_rest():
    team, handler = _run([diagnosis_reply(GOOD_CLAIM, UNCITED_CLAIM, root=("c1",))])
    assert team.diagnosis_status == "audited"
    assert [c.claim_id for c in team.supported_claims] == ["c1"]
    assert [(w.claim.claim_id, w.reason) for w in team.withdrawn_claims] == [("c2", "no_citations")]
    assert (team.claim_counts.supported, team.claim_counts.withdrawn) == (1, 1)
    assert team.claim_counts.by_reason == {"no_citations": 1}
    assert team.diagnosis.claims[1].claim_id == "c2"  # the diagnosis itself keeps it
    assert handler.calls["auditor"] == 1
    (body,) = [
        b for b in handler.bodies if "Rubric, one check per point" in b["messages"][-1]["content"]
    ]
    user = body["messages"][-1]["content"]
    for criterion in AUDIT_RUBRIC:
        assert criterion in user
    withdrawn_part = user.split("Withdrawn claims")[1].split("Remediation plan")[0]
    assert '"claim_id": "c2"' in withdrawn_part and '"reason": "no_citations"' in withdrawn_part
    supported_part = user.split("Supported claims with their citations:")[1].split("Withdrawn")[0]
    assert '"claim_id": "c1"' in supported_part and '"claim_id": "c2"' not in supported_part
    assert "Source src-a, cited lines:\n1: Sample record one" in user
    # Accepted by the model, with a claim withdrawn: accepted with a warning.
    assert team.audit.verdict == "accepted_with_warning"
    assert "1 claims were withdrawn" in team.audit.warning
    closing = [e.payload.message.text for e in team.events if e.type == "message"][-1]
    assert (
        "1 claims supported, 1 withdrawn" in closing and "Withdrawn: c2 (no_citations)." in closing
    )


def test_a_rejecting_auditor_is_reported_as_audited_and_rejected():
    team, _ = _run([diagnosis_reply()], auditor=[judgment_reply("rejected")])
    assert team.diagnosis_status == "audited" and team.audit.verdict == "rejected"
    assert team.audit.warning is None  # nothing was withdrawn


def test_no_supported_claim_left_is_inconclusive():
    bare = {"claim_id": "c3", "text": "[stub] More.", "citations": []}
    team, handler = _run([diagnosis_reply(UNCITED_CLAIM, bare, root=("c2",))] * 2, auditor=[])
    assert team.diagnosis_repairs == 1
    assert team.diagnosis_status == "inconclusive"
    assert team.inconclusive_reason == "no supported claim remains"
    assert handler.calls["auditor"] == 0 and team.supported_claims == []
    assert [w.claim.claim_id for w in team.withdrawn_claims] == ["c2", "c3"]


def test_no_diagnosis_is_inconclusive_without_an_auditor_call():
    junk = text_reply('{"status": "ok", "output": {"root_cause": "x"}}')
    team, handler = _run([junk] * 9, auditor=[])
    assert team.diagnosis is None and team.diagnosis_status == "inconclusive"
    assert team.inconclusive_reason.startswith("the director produced no valid diagnosis")
    assert handler.calls["auditor"] == 0
    assert team.audit.verdict == "rejected" and "Inconclusive" in team.audit.warning
    assert team.evidence is None and team.withdrawn_claims == []
