"""The director's optional plan json_schema and repair sampling, both off by default, and
the schema inliner they use. Stub transport; no network."""

import json
import random

import pytest
from harness_support import (
    TEST_KEY,
    FakeClock,
    config,
    final_action,
    ledger,
    replies,
    request,
    run,
    text_reply,
)
from team_stub import (
    GOOD_CLAIM,
    TeamHandler,
    block,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    skills_config,
    summary_reply,
)
from test_harness_escalate import Answer, ok

from rookwise.harness import Harness, ToolLoop
from rookwise.harness.escalate import run_with_escalation
from rookwise.harness.loop import Tool
from rookwise.harness.request import JsonSchemaFormat, RequestError
from rookwise.harness.schema import SchemaError, inline_refs
from rookwise.harness.validate import payload_model
from rookwise.team.config import load_team_roles
from rookwise.team.models import Plan

ULTRA, NANO = "nemotron-3-ultra", "nemotron-3-nano"
SAMPLE = {
    "status": "ok",
    "output": {
        "summary": "[stub] A plan.",
        "blocks": [
            {"goal": "[stub] g", "tasks": [{"role": "r", "source_id": "s", "instruction": "i"}]}
        ],
    },
    "notes": "",
}
# SYNTHETIC: the first inc-01 plan reply's mistake, "notes" inside "output".
NOTES_INSIDE = {"status": "ok", "output": {**SAMPLE["output"], "notes": ""}}


# -- a small JSON Schema validator for the keywords pydantic emits here (test only) --------


def _valid(value, schema, defs):
    if "$ref" in schema:
        return _valid(value, defs[schema["$ref"].split("/")[-1]], defs)
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict) or any(k not in value for k in schema.get("required", [])):
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            return False
        return all(_valid(value[k], s, defs) for k, s in properties.items() if k in value)
    if kind == "array":
        return (
            isinstance(value, list)
            and len(value) >= schema.get("minItems", 0)
            and all(_valid(v, schema["items"], defs) for v in value)
        )
    if kind == "string":
        return (
            isinstance(value, str)
            and len(value) >= schema.get("minLength", 0)
            and value in schema.get("enum", [value])
        )
    return True


def _validates(value, schema):
    return _valid(value, schema, schema.get("$defs", {}))


# -- the inliner ---------------------------------------------------------------------------


def test_the_inlined_plan_schema_has_no_ref_and_validates_like_the_original():
    original = payload_model(Plan).model_json_schema()
    before = json.dumps(original, sort_keys=True)
    inlined = inline_refs(original)
    assert "$ref" not in json.dumps(inlined) and "$defs" not in inlined
    assert json.dumps(original, sort_keys=True) == before  # the input is not changed
    for sample, expected in ((SAMPLE, True), (NOTES_INSIDE, False), ({"status": "ok"}, False)):
        assert _validates(sample, original) is expected
        assert _validates(sample, inlined) is expected
    payload_model(Plan).model_validate(SAMPLE)  # the sample is a real plan payload


def test_recursive_and_unknown_references_fail_loudly():
    recursive = {
        "$defs": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}},
        "$ref": "#/$defs/Node",
    }
    with pytest.raises(SchemaError, match="recursive \\$ref: Node -> Node"):
        inline_refs(recursive)
    with pytest.raises(SchemaError, match="names no definition"):
        inline_refs({"$ref": "#/$defs/Missing"})
    with pytest.raises(SchemaError, match="only local"):
        inline_refs({"$ref": "https://example.com/schema.json"})


# -- the director's options through the team -----------------------------------------------


def _director_config(**options):
    cfg = skills_config()
    cfg["roles"]["stub-director"].update(options)
    return cfg


def _team(cfg, *director):
    handler = TeamHandler(
        director=list(director) or [plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    run_stub_team(handler, run_usd="0.5", config=cfg)
    return handler


def test_the_options_off_leave_every_request_as_it_was():
    absent = _team(skills_config())  # the config as it was before the options existed
    off = _team(_director_config(plan_response_format=None, repair_temperature=None))
    assert off.bodies == absent.bodies
    assert all("response_format" not in b and "temperature" not in b for b in off.bodies)
    assert load_team_roles(skills_config()).director.plan_response_format is None


def test_json_schema_on_adds_the_wrapped_format_to_the_plan_call_only():
    handler = _team(_director_config(plan_response_format="json_schema"))
    plan, *others = handler.bodies
    wrapped = plan["response_format"]
    assert set(wrapped) == {"type", "json_schema"} and wrapped["type"] == "json_schema"
    assert set(wrapped["json_schema"]) == {"name", "schema", "strict"}
    assert wrapped["json_schema"]["name"] == "PlanPayload" and wrapped["json_schema"]["strict"]
    schema = wrapped["json_schema"]["schema"]
    assert schema == inline_refs(payload_model(Plan).model_json_schema())
    assert "$ref" not in json.dumps(schema) and "tools" not in plan
    assert all("response_format" not in b for b in others)


def test_the_options_are_checked_when_the_roles_load():
    with pytest.raises(ValueError, match="null or json_schema"):
        load_team_roles(_director_config(plan_response_format="json_object"))
    with pytest.raises(ValueError, match="in 0..2"):
        load_team_roles(_director_config(repair_temperature=3))
    cfg = skills_config()
    cfg["roles"]["stub-manager"]["plan_response_format"] = "json_schema"
    with pytest.raises(ValueError, match="only the director has a plan call"):
        load_team_roles(cfg)


def test_the_director_repair_temperature_reaches_its_reprompt():
    handler = _team(
        _director_config(repair_temperature=0.7), text_reply("not json"), plan_reply(block(1))
    )
    first, second = handler.bodies[:2]
    assert "temperature" not in first and second["temperature"] == 0.7
    assert all("temperature" not in b for b in handler.bodies[2:])  # other agents unchanged


# -- the guards and the repair sampling in the harness -------------------------------------


def _harness(handler, book):
    return Harness(
        book,
        config=config(),
        api_key=TEST_KEY,
        transport=handler.transport(),
        clock=FakeClock(),
        rng=random.Random(0),
    )


def _schema_format():
    return JsonSchemaFormat(name="Answer", schema={"type": "object"}, strict=True)


async def _add(args, ctx):
    return args["a"] + args["b"]


ADD = Tool("add", "Add two integers.", {"type": "object", "properties": {}}, _add)


@pytest.mark.parametrize(("model", "tools"), [(ULTRA, [ADD]), (NANO, [])])
def test_json_schema_is_refused_with_tools_or_in_json_protocol(model, tools):
    handler = replies(text_reply(json.dumps(ok())))

    async def main():
        async with _harness(handler, ledger()) as harness:
            req = request(model=model, response_format=_schema_format())
            return await ToolLoop(harness, tools).run(req)

    with pytest.raises(RequestError, match="json_schema response_format"):
        run(main())
    assert handler.bodies == []  # nothing was sent


def _escalate(handler, repair_temperature, model=ULTRA):
    async def main():
        async with _harness(handler, ledger()) as harness:
            req = request(model=model, messages=[{"role": "user", "content": "17 + 25?"}])
            return await run_with_escalation(
                ToolLoop(harness),
                req,
                Answer,
                config=config().escalation,
                repair_temperature=repair_temperature,
            )

    return run(main())


def test_repair_sampling_applies_only_from_the_first_reprompt():
    # A protocol error, then a schema error (a repair), then a valid answer.
    wrong = {"status": "ok", "output": {"sum": "x"}, "notes": ""}
    handler = replies(
        text_reply("not json"), text_reply(json.dumps(wrong)), text_reply(json.dumps(ok()))
    )
    result = _escalate(handler, 0.4)
    assert result.ok and [a.reason for a in result.attempts] == ["first", "repair"]
    assert [b.get("temperature") for b in handler.bodies] == [None, 0.4, 0.4]


def test_repair_sampling_off_sends_no_temperature_and_a_new_model_starts_clean():
    handler = replies(text_reply("not json"), text_reply(json.dumps(ok())))
    _escalate(handler, None)
    assert all("temperature" not in b for b in handler.bodies)
    # Super repeats an invalid reply, so the ladder moves to Ultra: a first step again.
    handler = replies(text_reply("bad"), text_reply("bad"), text_reply(json.dumps(ok())))
    result = _escalate(handler, 0.4, model="nemotron-3-super")
    assert result.final_model == ULTRA
    assert [b.get("temperature") for b in handler.bodies] == [None, 0.4, None]


def test_json_protocol_reprompts_get_the_temperature_too():
    handler = replies(text_reply("not json"), text_reply(final_action(ok())))

    async def main():
        async with _harness(handler, ledger()) as harness:
            req = request(model=NANO, messages=[{"role": "user", "content": "17 + 25?"}])
            return await ToolLoop(harness).run(req, repair_temperature=0.2)

    assert run(main()).status == "final"
    assert [b.get("temperature") for b in handler.bodies] == [None, 0.2]
