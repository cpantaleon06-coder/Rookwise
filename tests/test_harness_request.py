"""Request builder: per-model config, reasoning switch, wrapped json_schema, disallowed values."""

import json

import pytest
from harness_support import LIGHTNING, ULTRA, config, request

from rookwise.harness.request import (
    JsonObjectFormat,
    JsonSchemaFormat,
    RequestError,
    build_request,
)

NANO = "nemotron-3-nano"
SCHEMA = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}


def test_body_streams_with_usage_and_reasoning_off_by_default():
    built = build_request(request(max_tokens=None), config())
    body = built.body
    assert body["model"] == "nvidia/Nemotron-3_5-Lightning"
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == config().model(LIGHTNING).max_tokens == built.max_tokens
    for absent in ("temperature", "top_p", "reasoning_effort", "response_format"):
        assert absent not in body


def test_reasoning_and_sampling_overrides():
    body = build_request(request(reasoning=True, temperature=0.2, top_p=0.9), config()).body
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    assert body["temperature"] == 0.2 and body["top_p"] == 0.9


def test_json_schema_is_always_wrapped():
    fmt = JsonSchemaFormat(name="city_fact", schema=SCHEMA)
    body = build_request(request(response_format=fmt), config()).body
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "city_fact", "schema": SCHEMA, "strict": True},
    }


def test_reasoning_effort_none_is_never_sent_to_nano():
    with pytest.raises(RequestError, match="disallowed"):
        build_request(request(model=NANO, reasoning_effort="none"), config())
    assert "reasoning_effort" not in build_request(request(model=NANO), config()).body
    body = build_request(request(model=ULTRA, reasoning_effort="none"), config()).body
    assert body["reasoning_effort"] == "none"


def test_input_estimate_overestimates_and_can_be_overridden():
    req = request(messages=[{"role": "user", "content": "x" * 400}])
    built = build_request(req, config())
    assert built.input_tokens_estimate >= len(json.dumps(built.body["messages"])) / 4
    assert built.worst_case_tokens == built.input_tokens_estimate + built.max_tokens
    assert build_request(request(input_tokens_estimate=77), config()).input_tokens_estimate == 77


def test_invalid_requests_are_refused():
    with pytest.raises(RequestError):
        build_request(request(messages=[]), config())
    with pytest.raises(RequestError):
        build_request(request(messages=[{"content": "no role"}]), config())
    with pytest.raises(RequestError):
        build_request(request(max_tokens=0), config())


ADD = {
    "type": "function",
    "function": {"name": "add", "description": "Add.", "parameters": {"type": "object"}},
}


def test_tools_and_tool_choice_are_sent():
    body = build_request(request(tools=(ADD,), tool_choice="auto"), config()).body
    assert body["tools"] == [ADD] and body["tool_choice"] == "auto"
    assert "tools" not in build_request(request(), config()).body


def test_tools_with_response_format_or_tool_choice_alone_are_refused():
    fmt = JsonSchemaFormat(name="x", schema=SCHEMA)
    with pytest.raises(RequestError, match="tools cannot be combined"):
        build_request(request(tools=(ADD,), response_format=fmt), config())
    with pytest.raises(RequestError, match="tool_choice needs tools"):
        build_request(request(tool_choice="auto"), config())


def test_json_object_format_and_the_max_tokens_cap():
    body = build_request(request(response_format=JsonObjectFormat()), config()).body
    assert body["response_format"] == {"type": "json_object"}
    cap = config().model(LIGHTNING).max_tokens_cap
    assert build_request(request(max_tokens=cap), config()).max_tokens == cap
    with pytest.raises(RequestError):
        build_request(request(max_tokens=cap + 1), config())


def test_loop_protocols_and_ladder_follow_the_tool_probe():
    cfg = config()
    protocols = {alias: m.loop_protocol for alias, m in cfg.models.items()}
    assert protocols == {
        "nemotron-3-ultra": "native_tools",
        "nemotron-3-super": "native_tools",
        "nemotron-3.5-lightning": "native_tools",
        "nemotron-3-nano": "json_protocol",
    }
    assert cfg.escalation.next[LIGHTNING] == "nemotron-3-super"
    assert cfg.escalation.next[NANO] == "nemotron-3-super"
    assert cfg.escalation.next["nemotron-3-super"] == ULTRA
    assert ULTRA not in cfg.escalation.next
    assert cfg.length_retry.retries == 1
