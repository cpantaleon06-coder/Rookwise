"""The caps on one operator reply: said in the operator prompt and the log-reading skill,
checked by the findings model. Stub transport; no network."""

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
from rookwise.team.models import findings_model

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


def test_too_many_citations_in_a_claim_fail_with_the_rule():
    with pytest.raises(ValidationError) as failure:
        _model().model_validate(_findings(citations=6))
    message = str(failure.value)
    assert "claim 'c1' has 6 citations; give at most 5" in message
    assert "first and last occurrence of a repeated line" in message


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


def test_an_operator_over_the_cap_is_asked_to_repair_within_it():
    over = {**GOOD_CLAIM, "citations": [GOOD_CLAIM["citations"][0]] * 6}
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(over), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and handler.calls["operator"] == 2
    system = handler.bodies[1]["messages"][0]["content"]  # the operator's first request
    assert "Report at most 4 claims, each with at most 5 citations." in system
    repair = handler.bodies[2]["messages"][-1]["content"]
    assert "claim 'c1' has 6 citations; give at most 5" in repair
