"""Request builder: per-model config, reasoning switch, wrapped json_schema, disallowed values."""

import json

import pytest
from harness_support import LIGHTNING, ULTRA, config, request

from rookwise.harness.request import JsonSchemaFormat, RequestError, build_request

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
