"""Normalized stream events, the same for every model and for live, record and replay.

A successful stream is: `StreamStart`, any number of `TextDelta`, `ReasoningDelta` and
`ToolCallDelta`, one `UsageEvent`, then `Finish`. A failed attempt yields an
`ErrorEvent`; the stream then either retries (a new `StreamStart` follows) or raises.
Events are frozen pydantic models with a `type` tag, like the contracts in
`rookwise.schemas`, so a cassette can store them as JSON and read them back unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, NonNegativeInt, TypeAdapter

# The error taxonomy (see retry.py). The first four are retryable.
ErrorKind = Literal[
    "rate_limited",
    "timeout",
    "server",
    "connection",
    "validation",
    "auth",
    "not_found",
    "client",
    "stream_interrupted",
    "protocol",
]


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StreamStart(_Event):
    """The server accepted the request (HTTP 200) for this attempt."""

    type: Literal["stream_start"] = "stream_start"
    model: str
    model_id: str
    attempt: int = Field(ge=1)


class TextDelta(_Event):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ReasoningDelta(_Event):
    """Reasoning text, read from the first configured field that carries it, counted once."""

    type: Literal["reasoning_delta"] = "reasoning_delta"
    text: str


class ToolCallDelta(_Event):
    """A fragment of a native tool call, as streamed (see `assemble_tool_calls`).

    The first fragment of a call carries `id` and `name`; later ones only an `arguments`
    piece (VERIFIED in the tool-calling probe, HARNESS_RESEARCH.md).
    """

    type: Literal["tool_call_delta"] = "tool_call_delta"
    index: int = Field(ge=0)
    id: str | None = None
    name: str | None = None
    arguments: str = ""


class UsageEvent(_Event):
    """Token counts charged to the ledger. `estimated` is true when the API sent none."""

    type: Literal["usage"] = "usage"
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cached_tokens: NonNegativeInt = 0
    reasoning_tokens: NonNegativeInt = 0
    estimated: bool = False


class Finish(_Event):
    """The call is settled in the ledger. `finish_reason` is None when the server sent none."""

    type: Literal["finish"] = "finish"
    finish_reason: str | None
    usd: NonNegativeFloat
    usage_estimated: bool
    cancelled: bool = False


class ErrorEvent(_Event):
    """An attempt failed. `retryable` says whether another attempt follows."""

    type: Literal["error"] = "error"
    kind: ErrorKind
    message: str
    status_code: int | None = None
    retryable: bool
    attempt: int = Field(ge=1)


Event = Annotated[
    StreamStart | TextDelta | ReasoningDelta | ToolCallDelta | UsageEvent | Finish | ErrorEvent,
    Field(discriminator="type"),
]
EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


class ToolCall(_Event):
    """A complete native tool call. `arguments` is the raw JSON text the model sent."""

    id: str
    name: str
    arguments: str


def assemble_tool_calls(fragments: Iterable[ToolCallDelta]) -> tuple[ToolCall, ...]:
    """Join fragments per `index`: the first non-empty id and name win, arguments are
    concatenated. Nano sent a late fragment that repeated `id` as null, which is ignored.
    A call without an id gets `call_<index>`; one without a name gets ""."""
    calls: dict[int, dict[str, str]] = {}
    for piece in fragments:
        call = calls.setdefault(piece.index, {"id": "", "name": "", "arguments": ""})
        call["id"] = call["id"] or (piece.id or "")
        call["name"] = call["name"] or (piece.name or "")
        call["arguments"] += piece.arguments
    return tuple(
        ToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments=c["arguments"])
        for i, c in sorted(calls.items())
    )
