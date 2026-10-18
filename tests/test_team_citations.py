"""Single-line citations: the operator's output schema rejects a quote with a line break,
so the harness asks for a repair before the evidence check ever sees it. No network."""

import dataclasses

import pytest
from pydantic import ValidationError
from team_stub import (
    BUNDLE,
    GOOD_CLAIM,
    TeamHandler,
    block,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.evidence import Citation, Claim, EvidenceBundle, verify
from rookwise.harness import load_config
from rookwise.harness.config import EscalationConfig
from rookwise.harness.validate import payload_model
from rookwise.team.auditor import AUDITOR_PROMPT
from rookwise.team.flow import OPERATOR_PROMPT
from rookwise.team.models import Findings, SourceCitation

TWO_LINES = {
    "claim_id": "c1",
    "text": "[stub] The widget weighs 12 units and is blue.",
    "citations": [
        {
            "source_id": "src-a",
            "line_start": 1,
            "line_end": 2,
            "quote": "the widget weighs 12 units.\nSample record two: the widget is blue.",
        }
    ],
}


def _citation(quote: str, line_start: int = 1, line_end: int = 1) -> SourceCitation:
    return SourceCitation(source_id="src-a", line_start=line_start, line_end=line_end, quote=quote)


@pytest.mark.parametrize("quote", ["one\ntwo", "one\r\ntwo", "one\rtwo", "one\n"])
def test_a_quote_with_a_line_break_fails_validation(quote):
    with pytest.raises(ValidationError, match="the quote must be a single line"):
        _citation(quote)


def test_a_one_line_quote_may_span_a_range_and_passes_the_unchanged_evidence_check():
    spanning = _citation("the widget weighs 12 units. Sample record two:", 1, 2)
    single = _citation("the widget is blue.", 2, 2)
    claim = Findings.model_validate(
        {
            "summary": "[stub]",
            "claims": [{"claim_id": "c1", "text": "[stub]", "citations": [spanning, single]}],
        }
    ).claims[0]
    report = verify(BUNDLE, [claim.claim()])
    assert report.citation_verified_rate == 1.0 and report.all_supported


def test_the_citation_schema_has_exactly_four_required_fields():
    schema = payload_model(Findings).model_json_schema()["$defs"]["SourceCitation"]
    assert schema["additionalProperties"] is False
    assert sorted(schema["properties"]) == ["line_end", "line_start", "quote", "source_id"]
    assert sorted(schema["required"]) == ["line_end", "line_start", "quote", "source_id"]
    assert "single line" in schema["properties"]["quote"]["description"]
    with pytest.raises(ValidationError):  # the field names the first live run invented
        SourceCitation.model_validate(
            {"source_id": "src-a", "start": 1, "end": 1, "quote": "the widget is blue."}
        )


def test_the_prompts_ask_for_single_line_quotes():
    for field in ("source_id", "line_start", "line_end", "quote"):
        assert field in OPERATOR_PROMPT and field in AUDITOR_PROMPT
    assert "single line" in OPERATOR_PROMPT and "single line" in AUDITOR_PROMPT
    assert "line-number prefix" in OPERATOR_PROMPT


def test_a_multi_line_quote_is_repaired_before_the_evidence_check():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(TWO_LINES), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    recorded = [e.payload.attempt for e in team.events if e.type == "attempt_recorded"]
    attempts = [a for a in recorded if a.task_id == "t-1"]
    assert [a.reason for a in attempts] == ["first", "repair"]
    assert any("the quote must be a single line" in e for e in attempts[0].validation_errors)
    # The repair message names the error, so the model can fix the format.
    repair = handler.bodies[2]["messages"][-1]["content"]
    assert repair.startswith("VALIDATION ERROR") and "single line" in repair
    (result,) = [e.payload for e in team.events if e.type == "task_result"]
    assert result.label == "ok_after_retry"
    # Only the repaired, single-line quote reached the evidence check.
    assert team.evidence.citations_total == 1 and team.evidence.citation_verified_rate == 1.0


def test_a_multi_line_quote_counts_toward_the_repair_limit():
    no_repairs = dataclasses.replace(load_config(env={}), escalation=EscalationConfig(0, {}))
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(TWO_LINES), findings_reply(TWO_LINES)],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5", harness_config=no_repairs)
    (task,) = team.blocks[0].tasks
    assert task.status == "failed" and task.findings is None
    assert handler.calls["operator"] == 2  # no repair; each operator got one attempt
    assert team.evidence.citations_total == 0  # nothing failed late in the evidence check


def test_the_evidence_check_itself_is_unchanged_for_multi_line_quotes():
    bundle = EvidenceBundle(sources={"s": "alpha beta\ngamma delta\n"})
    claim = Claim(
        claim_id="c",
        text="t",
        citations=[Citation(source_id="s", line_start=1, line_end=2, quote="beta\ngamma")],
    )
    assert verify(bundle, [claim]).citation_verified_rate == 1.0
