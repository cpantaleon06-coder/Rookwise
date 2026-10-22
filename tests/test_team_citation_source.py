"""Operator citations take their source from the assigned slice, not from the model. The
quote and line checks are unchanged. Stub transport; no network."""

import pytest
from pydantic import ValidationError
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

from rookwise.evidence import EvidenceBundle
from rookwise.team.models import CitationLog, SliceAssignment, findings_model

# SYNTHETIC: two sources, so a citation can name the other one.
BUNDLE = EvidenceBundle(
    sources={
        "logs/app.log": "2026-03-04T03:00:00Z INFO start\n2026-03-04T03:01:00Z ERROR pool full\n",
        "ticket.md": "# SYNTHETIC ticket\nThe api is slow.\n",
    }
)
REF = "store://run_x/slices/logs/app.log:1-2"


def _assignment():
    assignment = SliceAssignment()
    assignment.assign("t-1", "logs/app.log", REF)
    return assignment


def _findings(source_id, line=2, quote="2026-03-04T03:01:00Z ERROR pool full", **extra):
    citation = {"line_start": line, "line_end": line, "quote": quote, **extra}
    if source_id is not ...:
        citation["source_id"] = source_id
    claim = {"claim_id": "c1", "text": "[stub] The pool is full.", "citations": [citation]}
    return {"summary": "[stub]", "claims": [claim]}


@pytest.mark.parametrize(
    "value",
    [
        REF,
        "store://run_x/slices/logs/app.log:1-1532",  # another range of the same source
        "store://run_x/slices/logs/app.log:194",
        "store://run_x/slices/logs/app.log",
        "logs/app.log:1-2",
        "logs/app.log:7",
        None,
        "",
        "  ",
    ],
)
def test_forms_of_the_assigned_slice_are_recognized(value):
    assert _assignment().names_the_slice(value)


@pytest.mark.parametrize(
    "value",
    [
        "logs/app.log",  # already the source id: nothing to derive
        "ticket.md",
        "store://run_x/slices/ticket.md:1-2",
        "logs/app.log.bak",
        "logs/app.log:1-2-3",
        "app.log",
    ],
)
def test_other_values_are_not_the_slice(value):
    assert not _assignment().names_the_slice(value)


def test_a_store_reference_or_a_missing_source_is_derived_and_counted():
    assignment = _assignment()
    model = findings_model(BUNDLE, CitationLog(), assignment)
    for value in (REF, ..., "logs/app.log:2"):
        findings = model.model_validate(_findings(value))
        assert findings.claims[0].citations[0].source_id == "logs/app.log"
    findings = model.model_validate(_findings("logs/app.log"))  # nothing to derive
    assert assignment.normalized == 3 and assignment.by_task == {"t-1": 3}


def test_the_quote_and_line_checks_are_unchanged():
    model = findings_model(BUNDLE, None, _assignment())
    with pytest.raises(ValidationError, match="the quote is not part of one line"):
        model.model_validate(_findings(REF, quote="2026-03-04T03:01:00Z ERROR pool empty"))
    with pytest.raises(ValidationError, match="lines 9-9 are not within 1-2"):
        model.model_validate(_findings(REF, line=9))


def test_another_source_of_the_run_is_never_accepted():
    model = findings_model(BUNDLE, None, _assignment())
    with pytest.raises(ValidationError, match="'ticket.md' is not the slice you were given"):
        model.model_validate(_findings("ticket.md", line=2, quote="The api is slow."))
    with pytest.raises(ValidationError, match="cite its lines with source_id 'logs/app.log'"):
        model.model_validate(_findings("store://run_x/slices/ticket.md:1-2", line=2))


def test_without_an_assignment_the_model_is_as_before():
    model = findings_model(BUNDLE)
    with pytest.raises(ValidationError, match="there is no source"):
        model.model_validate(_findings(REF))
    model.model_validate(_findings("ticket.md", line=2, quote="The api is slow."))
    assignment = SliceAssignment()  # assigned to nothing (between calls)
    findings_model(BUNDLE, None, assignment).model_validate(_findings("logs/app.log"))
    assert assignment.normalized == 0


def _store_ref_claim():
    citation = {**GOOD_CLAIM["citations"][0], "source_id": f"store://{RUN_ID}/slices/src-a:1-2"}
    return {**GOOD_CLAIM, "citations": [citation]}


def test_the_team_accepts_a_slice_reference_on_the_first_reply():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(_store_ref_claim())],  # one reply: no repair is scripted
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and handler.calls["operator"] == 1
    assert task.findings.claims[0].citations[0].source_id == "src-a"
    assert team.citation_source_normalizations == {"t-1": 1}
    assert team.citation_log[0].citations[0].ok  # logged after the source is derived


def test_the_team_asks_for_a_repair_when_an_operator_cites_another_source():
    other = {**GOOD_CLAIM["citations"][0], "source_id": "ticket.md"}
    # ticket.md is a real source of the run, empty, so no operator task reads it.
    bundle = EvidenceBundle(sources={"src-a": BUNDLE_A, "ticket.md": ""})
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[
            findings_reply({**GOOD_CLAIM, "citations": [other]}),
            findings_reply(GOOD_CLAIM),  # the repair, citing src-a
        ],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5", bundle=bundle)
    (task,) = team.blocks[0].tasks
    assert task.status == "ok" and handler.calls["operator"] == 2
    repair = next(
        b for b in handler.bodies if "is not the slice you were given" in str(b["messages"][-1])
    )
    assert "'ticket.md' is not the slice you were given" in repair["messages"][-1]["content"]


BUNDLE_A = (
    "Sample record one: the widget weighs 12 units.\nSample record two: the widget is blue.\n"
)
