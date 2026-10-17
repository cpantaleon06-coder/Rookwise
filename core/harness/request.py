"""Build the chat-completions body for one call from a `ChatRequest` and the model config.

Every body streams with `stream_options.include_usage`, so the final chunk carries the
usage the ledger charges (VERIFIED for all four models, HARNESS_RESEARCH.md, streaming
probe). Reasoning is switched with `chat_template_kwargs.enable_thinking`. A JSON
schema is always sent in the wrapped form
`{"type": "json_schema", "json_schema": {"name", "schema", "strict"}}`; the bare form
returns HTTP 422 (VERIFIED, smoke test 2026-10-13). Values listed under `disallowed`
in config/harness.json are refused before anything is sent.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from rookwise.harness.config import HarnessConfig, ModelConfig
from rookwise.money import ZERO_USD
from rookwise.schemas import Level


class RequestError(ValueError):
    """The request cannot be sent as built (bad input or a value the model must not get)."""


@dataclass(frozen=True)
class JsonSchemaFormat:
    name: str
    schema: Mapping[str, Any]
    strict: bool = True

    def to_api(self) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {"name": self.name, "schema": dict(self.schema), "strict": self.strict},
        }


@dataclass(frozen=True)
class JsonObjectFormat:
    """`{"type": "json_object"}`: any JSON object (the JSON action protocol uses it)."""

    def to_api(self) -> dict[str, Any]:
        return {"type": "json_object"}


@dataclass(frozen=True)
class ChatRequest:
    """One model call. `model` is an alias from config/prices.json.

    `run_id`, `level`, `task_id`, `skills`, `usd_predicted` and `budget_id` (the ledger
    allocation the call is drawn from, None for the run) go to the ledger, not to
    the API. `usd_predicted` is the caller's cost prediction, a Decimal; zero means none
    was made.
    Fields left None take the model's defaults from config/harness.json.
    `input_tokens_estimate` overrides the characters-based estimate used to reserve.
    """

    model: str
    messages: Sequence[Mapping[str, Any]]
    run_id: str
    level: Level
    task_id: str
    max_tokens: int | None = None
    reasoning: bool | None = None
    reasoning_effort: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    response_format: JsonSchemaFormat | JsonObjectFormat | None = None
    tools: tuple[Mapping[str, Any], ...] = ()
    tool_choice: str | Mapping[str, Any] | None = None
    usd_predicted: Decimal = ZERO_USD
    skills: tuple[str, ...] = ()
    input_tokens_estimate: int | None = None
    budget_id: str | None = None


@dataclass(frozen=True)
class BuiltRequest:
    request: ChatRequest
    model: ModelConfig
    body: dict[str, Any] = field(repr=False)
    max_tokens: int
    input_tokens_estimate: int

    @property
    def worst_case_tokens(self) -> int:
        return self.input_tokens_estimate + self.max_tokens


def estimate_input_tokens(
    messages: Sequence[Mapping[str, Any]],
    response_format: Mapping[str, Any] | None,
    chars_per_token: float,
    margin_tokens: int,
) -> int:
    """A deliberately high estimate: JSON characters / chars_per_token, plus a margin."""
    payload = json.dumps({"messages": list(messages), "response_format": response_format})
    return math.ceil(len(payload) / chars_per_token) + margin_tokens


def build_request(request: ChatRequest, config: HarnessConfig) -> BuiltRequest:
    model = config.model(request.model)
    if not request.messages:
        raise RequestError("messages must not be empty")
    for message in request.messages:
        if not isinstance(message, Mapping) or "role" not in message:
            raise RequestError("every message needs a role")
    max_tokens = request.max_tokens if request.max_tokens is not None else model.max_tokens
    if not 0 < max_tokens <= model.max_tokens_cap:
        raise RequestError(f"max_tokens must be in 1..{model.max_tokens_cap} for {model.alias}")
    reasoning = request.reasoning if request.reasoning is not None else model.reasoning

    body: dict[str, Any] = {
        "model": model.model_id,
        "messages": [dict(m) for m in request.messages],
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": reasoning},
    }
    optional = {
        "temperature": request.temperature
        if request.temperature is not None
        else model.temperature,
        "top_p": request.top_p if request.top_p is not None else model.top_p,
        "reasoning_effort": request.reasoning_effort,
    }
    body.update({k: v for k, v in optional.items() if v is not None})
    if request.response_format is not None:
        body["response_format"] = request.response_format.to_api()
    if request.tools:
        if request.response_format is not None:
            # In the tool-calling probe every model skipped the tools when a json_schema
            # response_format came with them, so the combination is refused.
            raise RequestError("tools cannot be combined with response_format")
        body["tools"] = [dict(tool) for tool in request.tools]
        if request.tool_choice is not None:
            body["tool_choice"] = request.tool_choice
    elif request.tool_choice is not None:
        raise RequestError("tool_choice needs tools")

    for name, values in model.disallowed.items():
        if name in body and body[name] in values:
            raise RequestError(
                f"{name}={body[name]!r} is disallowed for {model.alias} (config/harness.json)"
            )

    estimate = request.input_tokens_estimate
    if estimate is None:
        estimate = estimate_input_tokens(
            body["messages"],
            body.get("response_format") or body.get("tools"),
            config.chars_per_token,
            config.margin_tokens,
        )
    return BuiltRequest(request, model, body, max_tokens, estimate)
