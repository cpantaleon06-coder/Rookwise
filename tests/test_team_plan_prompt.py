"""The director's plan prompt shows a literal example of the nested final result shape,
next to the unchanged JSON Schema. Stub transport; no network."""

import json

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

from rookwise.harness.validate import final_result_instructions, payload_model
from rookwise.team.flow import DIRECTOR_PROMPT
from rookwise.team.models import Plan


def _example():
    (line,) = [line for line in DIRECTOR_PROMPT.splitlines() if line.startswith('{"status"')]
    return json.loads(line)


def test_the_example_is_valid_json_with_notes_outside_output():
    example = _example()
    assert list(example) == ["status", "output", "notes"]
    assert list(example["output"]) == ["summary", "blocks"]
    assert list(example["output"]["blocks"][0]["tasks"][0]) == ["role", "source_id", "instruction"]
    payload_model(Plan).model_validate(example)  # it matches the schema it illustrates


def test_the_plan_request_carries_the_example_and_the_same_schema_text():
    handler = TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    run_stub_team(handler, run_usd="0.5")
    system = handler.bodies[0]["messages"][0]["content"]
    assert system.startswith(DIRECTOR_PROMPT)
    assert json.dumps(_example()) in system
    # The run's plan model has the same JSON Schema as `Plan`, so the text is unchanged.
    assert final_result_instructions(Plan) in system
