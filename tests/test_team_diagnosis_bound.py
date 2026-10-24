"""The director's diagnosis: its own output ceiling (config/skills.json) and its size
bound (config/budget.json), the same in the hierarchy and both single-model baselines. A
diagnosis over the bound keeps its first claims and citations by position, before any
check, with no repair. Stub transport; no network."""

import dataclasses

import pytest
from pydantic import ValidationError
from team_stub import (
    GOOD_CLAIM,
    TeamHandler,
    block,
    diagnosis_reply,
    findings_reply,
    judgment_reply,
    operator,
    plan_reply,
    run_stub_team,
    skills_config,
    summary_reply,
)

from rookwise.evidence import EvidenceBundle
from rookwise.harness import load_config
from rookwise.team import BudgetPolicy
from rookwise.team.config import load_budget_policy, load_team_roles
from rookwise.team.flow import DIAGNOSIS_PROMPT, Baseline, diagnosis_prompt
from rookwise.team.models import CitationLog, diagnosis_model, trim_claims

# SYNTHETIC: one source of ten numbered lines.
LINES = [f"2026-03-04T03:0{n}:00Z ERROR pool full n={n}" for n in range(10)]
TEN = EvidenceBundle(sources={"app.log": "\n".join(LINES) + "\n"})


def _citation(n):
    return {"source_id": "app.log", "line_start": n + 1, "line_end": n + 1, "quote": LINES[n]}


def _diagnosis(claims, citations, root=("c1",)):
    return {
        "root_cause": "[stub] The pool is full.",
        "category": "capacity_exhaustion",
        "claims": [
            {
                "claim_id": f"c{i + 1}",
                "text": "[stub] The pool is full.",
                "citations": [_citation(n) for n in range(citations)],
            }
            for i in range(claims)
        ],
        "root_cause_claim_ids": list(root),
        "remediation_plan": [
            {"action": "[stub] a", "why": "[stub] b", "risk": "[stub] c", "reversible": True}
        ],
    }


def _bounded(log=None):
    return diagnosis_model(TEN, log, max_claims=6, max_citations_per_claim=4)


def _config(diagnosis_tokens=4096):
    config = skills_config()
    config["roles"]["stub-director"]["diagnosis_max_output_tokens"] = diagnosis_tokens
    return config


def _max_tokens(handler, prompt):
    return [
        b["max_tokens"] for b in handler.bodies if b["messages"][0]["content"].startswith(prompt)
    ]


def test_the_ceiling_and_the_bound_are_config():
    director = load_team_roles().director
    assert (director.max_output_tokens, director.diagnosis_max_output_tokens) == (2048, 4096)
    assert director.diagnosis_tokens == 4096
    policy = load_budget_policy()
    assert (policy.diagnosis_max_claims, policy.diagnosis_max_citations_per_claim) == (6, 4)
    assert policy == BudgetPolicy()


def test_only_the_director_takes_a_diagnosis_ceiling():
    config = skills_config()
    config["roles"]["stub-manager"]["diagnosis_max_output_tokens"] = 4096
    with pytest.raises(ValueError, match="only the director has a diagnosis call"):
        load_team_roles(config)
    config = _config(diagnosis_tokens=0)
    with pytest.raises(ValueError, match="diagnosis_max_output_tokens"):
        load_team_roles(config)
    assert load_team_roles(skills_config()).director.diagnosis_tokens == 256  # falls back


def test_the_prompt_states_the_bound():
    prompt = diagnosis_prompt(
        BudgetPolicy(diagnosis_max_claims=3, diagnosis_max_citations_per_claim=2)
    )
    assert prompt.startswith(DIAGNOSIS_PROMPT)
    assert "Give at most 3 claims, each with at most 2 citations" in prompt


def test_a_diagnosis_over_the_bound_is_trimmed_by_position():
    log = CitationLog(task_id="diagnosis")
    diagnosis = _bounded(log).model_validate(_diagnosis(claims=8, citations=6))
    assert [c.claim_id for c in diagnosis.claims] == [f"c{n}" for n in range(1, 7)]
    assert all(
        [c.line_start for c in claim.citations] == [1, 2, 3, 4] for claim in diagnosis.claims
    )
    (reply,) = log.replies
    assert (reply.trimmed_claims, reply.trimmed, len(reply.citations)) == (2, 12, 24)


def test_the_trim_never_chooses_by_validity():
    data = _diagnosis(claims=1, citations=0)
    bad = {"source_id": "app.log", "line_start": 1, "line_end": 1, "quote": "not in the log"}
    data["claims"][0]["citations"] = [bad, bad, _citation(2), _citation(3), _citation(4)]
    log = CitationLog(task_id="diagnosis")
    diagnosis = _bounded(log).model_validate(data)  # shape only: bad quotes do not reject it
    assert [c.quote for c in diagnosis.claims[0].citations][:2] == ["not in the log"] * 2
    assert [c.ok for c in log.replies[0].citations] == [False, False, True, True]


def test_root_cause_ids_of_dropped_claims_are_dropped_too():
    data = _diagnosis(claims=8, citations=1, root=("c2", "c8"))
    trimmed, dropped = trim_claims(data, 6)
    assert dropped == 2 and trimmed["root_cause_claim_ids"] == ["c2"]
    assert _bounded().model_validate(data).root_cause_claim_ids == ["c2"]
    # Every root-cause claim dropped: the diagnosis has none left and fails validation.
    with pytest.raises(ValidationError):
        _bounded().model_validate(_diagnosis(claims=8, citations=1, root=("c7", "c8")))


def test_within_the_bound_nothing_changes():
    data = _diagnosis(claims=6, citations=4)
    assert trim_claims(data, 6) == (data, 0)
    log = CitationLog(task_id="diagnosis")
    _bounded(log).model_validate(data)
    assert (log.replies[0].trimmed_claims, log.replies[0].trimmed) == (0, 0)


def test_the_hierarchy_uses_the_diagnosis_ceiling_and_the_plan_keeps_its_own():
    many = [
        {**GOOD_CLAIM, "claim_id": f"c{n}", "citations": GOOD_CLAIM["citations"] * 5}
        for n in range(1, 9)
    ]
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        diagnosis=[diagnosis_reply(*many)],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5", config=_config())
    assert _max_tokens(handler, "You are the director of a team of AI agents. Split") == [256]
    assert _max_tokens(handler, DIAGNOSIS_PROMPT) == [4096]
    system = next(
        b["messages"][0]["content"]
        for b in handler.bodies
        if b["messages"][0]["content"].startswith(DIAGNOSIS_PROMPT)
    )
    assert "Give at most 6 claims, each with at most 4 citations" in system
    # Over the bound: trimmed, counted, and no repair call.
    assert handler.calls["diagnosis"] == 1 and team.diagnosis_repairs == 0
    assert len(team.diagnosis.claims) == 6
    assert (team.diagnosis_trimmed_claims, team.diagnosis_trimmed_citations) == (2, 6)
    assert "diagnosis" not in team.trimmed_citations  # operators' count stays apart


@pytest.mark.parametrize("model", ["nemotron-3-ultra", "nemotron-3.5-lightning"])
def test_both_baselines_use_the_same_diagnosis_ceiling_and_bound(model):
    handler = TeamHandler(operator=[findings_reply(GOOD_CLAIM)], diagnosis=[diagnosis_reply()])
    config = load_config(env={})
    no_ladder = dataclasses.replace(
        config, escalation=dataclasses.replace(config.escalation, next={})
    )
    run_stub_team(
        handler,
        run_usd="1.0",
        catalog=[operator("stub-baseline", "0.001", model=model)],
        harness_config=no_ladder,
        config=_config(),
        policy=BudgetPolicy(max_reassignments=0, task_limit_next_rung_reservations=0),
        baseline=Baseline(model=model, instruction="[stub] Read it.", default_role="stub-operator"),
    )
    (body,) = [
        b for b in handler.bodies if b["messages"][0]["content"].startswith(DIAGNOSIS_PROMPT)
    ]
    assert body["max_tokens"] == 4096
    assert "Give at most 6 claims, each with at most 4 citations" in body["messages"][0]["content"]
