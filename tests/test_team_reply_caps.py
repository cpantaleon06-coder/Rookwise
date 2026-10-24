"""The caps on one operator reply: said in the operator prompt and the log-reading skill.
A reply over the claim cap fails the findings model; a claim over the citation cap keeps
its first citations by position, before any check, with no repair. Stub transport; no
network."""

import pytest
from pydantic import ValidationError
from team_stub import (
    GOOD_CLAIM,
    TeamHandler,
    block,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.evidence import EvidenceBundle
from rookwise.skills import load_skill
from rookwise.team import BudgetPolicy
from rookwise.team.config import load_budget_policy
from rookwise.team.flow import OPERATOR_PROMPT, operator_prompt
from rookwise.team.models import CitationLog, SliceAssignment, findings_model, trim_citations

# SYNTHETIC: one source of ten numbered lines.
LINES = [f"2026-03-04T03:0{n}:00Z ERROR pool full n={n}" for n in range(10)]
BUNDLE = EvidenceBundle(sources={"app.log": "\n".join(LINES) + "\n"})


def _citation(n):
    return {"source_id": "app.log", "line_start": n + 1, "line_end": n + 1, "quote": LINES[n]}


def _findings(claims=1, citations=1):
    return {
        "summary": "[stub]",
        "claims": [
            {
                "claim_id": f"c{i + 1}",
                "text": "[stub] The pool is full.",
                "citations": [_citation(n) for n in range(citations)],
            }
            for i in range(claims)
        ],
    }


def _model():
    return findings_model(BUNDLE, max_claims=4, max_citations_per_claim=5)


def test_a_reply_within_the_caps_passes():
    _model().model_validate(_findings(claims=4, citations=5))


def test_a_claim_over_the_citation_cap_keeps_its_first_citations_by_position():
    findings = _model().model_validate(_findings(claims=2, citations=7))
    for claim in findings.claims:
        assert [c.line_start for c in claim.citations] == [1, 2, 3, 4, 5]


def test_the_trim_never_chooses_by_validity():
    # The first two citations are bad, the last two good: the trim keeps the first five
    # by position anyway, so the two bad ones stay and fail the check.
    bad = {"source_id": "app.log", "line_start": 1, "line_end": 1, "quote": "not in the log"}
    claim = {
        "claim_id": "c1",
        "text": "[stub] The pool is full.",
        "citations": [bad, bad, *[_citation(n) for n in range(2, 7)]],
    }
    kept, dropped = trim_citations({"summary": "[stub]", "claims": [claim]}, 5)
    assert dropped == 2
    assert kept["claims"][0]["citations"] == claim["citations"][:5]
    with pytest.raises(ValidationError, match="not part of one line"):
        _model().model_validate({"summary": "[stub]", "claims": [claim]})


def test_trimmed_citations_are_counted_in_the_citation_log():
    log = CitationLog(task_id="t-1")
    model = findings_model(BUNDLE, log, max_claims=4, max_citations_per_claim=5)
    model.model_validate(_findings(claims=2, citations=7))
    model.model_validate(_findings(claims=1, citations=3))
    first, second = log.replies
    assert (first.trimmed, len(first.citations)) == (4, 10)  # checks after the trim only
    assert (second.trimmed, len(second.citations)) == (0, 3)
    assert log.trimmed_by_task() == {"t-1": 4}


def test_the_trim_runs_before_the_source_is_derived_from_the_slice():
    log, assignment = CitationLog(task_id="t-1"), SliceAssignment()
    assignment.assign("t-1", "app.log", "store://run/slices/app.log#1")
    model = findings_model(BUNDLE, log, assignment, max_citations_per_claim=2)
    unnamed = [{**_citation(n), "source_id": ""} for n in range(4)]
    findings = model.model_validate(
        {"summary": "[stub]", "claims": [{"claim_id": "c1", "text": "x", "citations": unnamed}]}
    )
    assert len(findings.claims[0].citations) == 2
    assert assignment.by_task == {"t-1": 2}  # only the kept citations were derived
    assert log.replies[0].trimmed == 2


def test_a_reply_within_the_citation_cap_is_left_as_is():
    data = _findings(claims=2, citations=5)
    assert trim_citations(data, 5) == (data, 0)
    assert trim_citations(data, None) == (data, 0)
    assert trim_citations("not a dict", 5) == ("not a dict", 0)


def test_too_many_claims_fail():
    with pytest.raises(ValidationError, match="the reply has 5 claims; report at most 4"):
        _model().model_validate(_findings(claims=5))


def test_without_caps_the_model_is_as_before():
    findings_model(BUNDLE).model_validate(_findings(claims=6, citations=10))


def test_the_caps_are_config_and_checked():
    policy = load_budget_policy()
    assert (policy.operator_max_claims, policy.operator_max_citations_per_claim) == (4, 5)
    with pytest.raises(ValueError, match="at least 1"):
        BudgetPolicy(operator_max_citations_per_claim=0)


def test_the_prompt_and_the_skill_say_not_to_enumerate_matches():
    assert "never cite every matching line" in OPERATOR_PROMPT
    prompt = operator_prompt(
        BudgetPolicy(operator_max_claims=3, operator_max_citations_per_claim=2)
    )
    assert prompt.startswith(OPERATOR_PROMPT)
    assert prompt.endswith("Report at most 3 claims, each with at most 2 citations.")
    body = load_skill("log-reading").body
    assert "first and last occurrence" in body and "Never cite every match." in body


def test_an_operator_over_the_citation_cap_is_trimmed_without_a_repair():
    over = {**GOOD_CLAIM, "citations": [GOOD_CLAIM["citations"][0]] * 7}
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(over)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and handler.calls["operator"] == 1  # no repair call
    assert len(task.findings.claims[0].citations) == 5
    assert team.trimmed_citations == {"t-1": 2}
    system = handler.bodies[1]["messages"][0]["content"]  # the operator's first request
    assert "Report at most 4 claims, each with at most 5 citations." in system


def test_an_operator_over_the_claim_cap_is_still_asked_to_repair():
    claims = [{**GOOD_CLAIM, "claim_id": f"c{n}"} for n in range(1, 6)]
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(*claims), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and handler.calls["operator"] == 2
    repair = handler.bodies[2]["messages"][-1]["content"]
    assert "the reply has 5 claims; report at most 4" in repair
    assert team.trimmed_citations == {}
