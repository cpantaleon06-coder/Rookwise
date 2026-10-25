"""A `notes` field the director put inside `output` (plan and diagnosis) is moved to the
envelope before validation and counted; nothing else moves, and operators are not
affected. Stub transport; no network."""

import json

from harness_support import text_reply
from team_stub import (
    GOOD_CLAIM,
    TeamHandler,
    block,
    diagnosis_payload,
    findings_payload,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.team.models import hoist_notes


def _misplaced(payload: str, notes: str = "[stub] a note") -> bytes:
    value = json.loads(payload)
    value["output"]["notes"] = notes
    value.pop("notes", None)
    return text_reply(json.dumps(value))


def test_the_notes_move_to_the_envelope_and_nothing_else_moves():
    value = {"status": "ok", "output": {"summary": "s", "notes": "inner"}}
    moved, hoisted = hoist_notes(value)
    assert hoisted and moved == {"status": "ok", "output": {"summary": "s"}, "notes": "inner"}
    assert value["output"]["notes"] == "inner"  # the input is not changed


def test_both_notes_are_joined_and_empty_ones_drop_out():
    both = {"status": "ok", "output": {"notes": "inner"}, "notes": "outer"}
    assert hoist_notes(both)[0]["notes"] == "outer\ninner"
    empty_inner = {"status": "ok", "output": {"notes": ""}, "notes": "outer"}
    assert hoist_notes(empty_inner) == ({"status": "ok", "output": {}, "notes": "outer"}, True)
    empty_outer = {"status": "ok", "output": {"notes": ""}, "notes": ""}
    assert hoist_notes(empty_outer) == ({"status": "ok", "output": {}, "notes": ""}, True)


def test_nothing_happens_without_a_misplaced_notes_field():
    for value in (
        None,
        "text",
        {"status": "ok", "output": {"summary": "s"}, "notes": "n"},
        {"status": "ok", "output": ["notes"]},
        {"status": "ok", "output": {"notes": ["a list"]}, "notes": "outer"},
    ):
        assert hoist_notes(value) == (value, False)


def _team(director, diagnosis, operator=None):
    handler = TeamHandler(
        director=director,
        operator=operator or [text_reply(findings_payload(GOOD_CLAIM))],
        manager=[summary_reply()],
        diagnosis=diagnosis,
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5")
    return team, handler


def test_a_diagnosis_with_notes_in_its_output_passes_without_a_repair():
    team, handler = _team([plan_reply(block(1))], [_misplaced(diagnosis_payload())])
    assert handler.calls["diagnosis"] == 1 and team.diagnosis is not None
    assert team.notes_hoisted == 1


def test_a_plan_with_notes_in_its_output_passes_without_a_repair():
    plan = {"status": "ok", "output": {"summary": "[stub] A plan.", "blocks": [block(1)]}}
    team, handler = _team([_misplaced(json.dumps(plan))], [_misplaced(diagnosis_payload())])
    assert handler.calls["director"] == 1 and team.plan is not None
    assert team.notes_hoisted == 2  # the plan and the diagnosis


def test_operators_are_not_hoisted():
    value = json.loads(findings_payload(GOOD_CLAIM))
    value["output"]["notes"] = "[stub] an operator note"
    team, handler = _team(
        [plan_reply(block(1))],
        [text_reply(diagnosis_payload())],
        operator=[text_reply(json.dumps(value)), text_reply(findings_payload(GOOD_CLAIM))],
    )
    assert handler.calls["operator"] == 2  # rejected, then repaired
    repair = next(
        b for b in handler.bodies if b["messages"][-1]["content"].startswith("VALIDATION ERROR")
    )
    assert "output.notes: Extra inputs are not permitted" in repair["messages"][-1]["content"]
    assert team.notes_hoisted == 0
