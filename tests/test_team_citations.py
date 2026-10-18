"""Single-line citations: the operator's output schema rejects a quote with a line break,
so the harness asks for a repair before the evidence check ever sees it. No network."""

import dataclasses
import json

import pytest
from harness_support import text_reply
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
from rookwise.harness.validate import final_result_instructions, payload_model, validate_final
from rookwise.team.auditor import AUDITOR_PROMPT
from rookwise.team.flow import OPERATOR_PROMPT
from rookwise.team.models import Findings, SourceCitation, findings_model

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


# -- each quote inside a single source line (findings_model) ---------------------------------

# SYNTHETIC: five log lines shaped like the ones task t-6 of the second record run
# (2026-10-18) joined into one quote. The real cassette is not used.
LOG = (
    "2026-03-04T02:12:44Z INFO  deploy.agent received config bundle config_version=42\n"
    "2026-03-04T02:12:45Z INFO  config.diff db.pool.max_connections: 50 -> 5\n"
    "2026-03-04T02:12:45Z INFO  config.diff http.request_timeout_ms: 3000 -> 3000\n"
    "2026-03-04T02:12:46Z INFO  config reloaded config_version=42 restart=false\n"
    "2026-03-04T02:12:46Z INFO  db.pool resized max_connections=5 active=11 idle=2\n"
)
PIPE_JOINED = (
    "deploy.agent received config bundle config_version=42 | config.diff "
    "db.pool.max_connections: 50 -> 5 | config.diff http.request_timeout_ms: 3000 -> 3000 "
    "| config reloaded config_version=42 restart=false | db.pool resized max_connections=5 "
    "active=11 idle=2"
)
RUN_FINDINGS = findings_model(EvidenceBundle(sources={"log": LOG}))


def _findings(quote, line_start=1, line_end=5, source_id="log"):
    citation = {
        "source_id": source_id,
        "line_start": line_start,
        "line_end": line_end,
        "quote": quote,
    }
    claim = {"claim_id": "c1", "text": "[stub]", "citations": [citation]}
    return {"summary": "[stub]", "claims": [claim]}


def _errors(output):
    validation = validate_final({"status": "ok", "output": output}, RUN_FINDINGS)
    return validation.ok, list(validation.errors)


def test_the_run_bound_model_keeps_the_schema_the_prompt_shows():
    assert RUN_FINDINGS.__name__ == "Findings"
    assert final_result_instructions(RUN_FINDINGS) == final_result_instructions(Findings)


def test_a_quote_joined_with_pipes_fails_validation_with_a_repair_hint():
    ok, errors = _errors(_findings(PIPE_JOINED, 1, 5))
    assert not ok
    (error,) = errors
    assert error.startswith("output.claims.0.citations.0:")
    assert "joins lines with ' | '" in error and "one citation per line" in error
    # The evidence check alone would not catch every such quote: joined with spaces, a
    # quote over two lines passes it but not the single-line rule.
    spaced = "config_version=42 2026-03-04T02:12:45Z INFO config.diff"
    report = verify(
        EvidenceBundle(sources={"log": LOG}),
        [
            Claim(
                claim_id="c",
                text="t",
                citations=[Citation(source_id="log", line_start=1, line_end=2, quote=spaced)],
            )
        ],
    )
    assert report.citation_verified_rate == 1.0
    ok, errors = _errors(_findings(spaced, 1, 2))
    assert not ok and "is not part of one line" in errors[0]


@pytest.mark.parametrize(
    ("quote", "line_start", "line_end"),
    [
        ("2026-03-04T02:12:45Z INFO  config.diff db.pool.max_connections: 50 -> 5", 2, 2),
        ("db.pool.max_connections: 50 -> 5", 1, 5),  # part of one line inside the range
        ("config   reloaded\tconfig_version=42", 4, 4),  # whitespace is normalized
    ],
)
def test_a_quote_inside_one_line_of_the_range_passes(quote, line_start, line_end):
    assert _errors(_findings(quote, line_start, line_end)) == (True, [])


@pytest.mark.parametrize(
    ("quote", "line_start", "line_end", "source_id", "expected"),
    [
        ("db.pool.max_connections: 50 -> 5", 3, 5, "log", "is not part of one line"),
        ("db.pool.max_connections: 50 -> 5", 2, 9, "log", "are not within 1-5"),
        ("db.pool.max_connections: 50 -> 5", 2, 2, "other", "there is no source 'other'"),
        ("   ", 2, 2, "log", "the quote is empty"),
        ("max_connections: 50 -> 6", 2, 2, "log", "is not part of one line"),
    ],
)
def test_other_quotes_outside_one_line_fail(quote, line_start, line_end, source_id, expected):
    ok, errors = _errors(_findings(quote, line_start, line_end, source_id))
    assert not ok and expected in errors[0]


def test_a_pipe_joined_quote_is_repaired_and_counts_toward_the_repair_limit():
    bundle = EvidenceBundle(sources={"log": LOG})
    good = _findings("db.pool resized max_connections=5 active=11 idle=2", 5, 5)
    payload = json.dumps({"status": "ok", "output": _findings(PIPE_JOINED), "notes": ""})
    repaired = json.dumps({"status": "ok", "output": good, "notes": ""})
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[text_reply(payload), text_reply(repaired)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5", bundle=bundle)
    recorded = [e.payload.attempt for e in team.events if e.type == "attempt_recorded"]
    attempts = [a for a in recorded if a.task_id == "t-1"]
    assert [a.reason for a in attempts] == ["first", "repair"]
    assert "joins lines with ' | '" in attempts[0].validation_errors[0]
    assert team.evidence.all_supported and team.evidence.citations_total == 1

    no_repairs = dataclasses.replace(load_config(env={}), escalation=EscalationConfig(0, {}))
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[text_reply(payload), text_reply(payload)],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5", bundle=bundle, harness_config=no_repairs)
    (task,) = team.blocks[0].tasks
    assert task.status == "failed" and handler.calls["operator"] == 2


def test_the_prompts_ask_for_one_verbatim_line_per_citation():
    for prompt in (OPERATOR_PROMPT, AUDITOR_PROMPT):
        assert "timestamp" in prompt and "several" in prompt
    assert "Never join lines" in OPERATOR_PROMPT and '" | "' in OPERATOR_PROMPT
    assert "never joined" in AUDITOR_PROMPT
