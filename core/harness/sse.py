"""Server-sent events decoding and chunk normalization for chat-completion streams.

Shapes observed in the streaming probe (HARNESS_RESEARCH.md, 2026-10-16 UTC), all VERIFIED:
- Events are `data: <json>` lines separated by blank lines; the stream ends with
  `data: [DONE]`. No comments or `event:` lines were seen, but both are tolerated.
- The final JSON chunk has `choices: []` and the final `usage`. Ultra and Nano also put
  running usage totals on every chunk; those are only a lower bound until the end.
- The first chunk is a role chunk. `delta.content` is a string, "" or absent, never
  null so far (null is tolerated). Lightning's finish chunk has `delta: {}`.
- Reasoning text arrives in `reasoning_content` (Ultra), `reasoning` (Nano) or both with
  identical text (Super, Lightning), so it is read from the first configured field only.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rookwise.harness.cost import parse_usage
from rookwise.harness.events import ReasoningDelta, TextDelta
from rookwise.harness.retry import ApiError, classify_status
from rookwise.ledger import Usage

DONE = "[DONE]"


class SSEDecoder:
    """Incremental decoder: feed raw bytes as they arrive, get complete `data` payloads.

    Handles events split across reads, CRLF or LF line endings, multi-line data (joined
    with a newline) and comment lines (starting with ":"), which are ignored.
    """

    def __init__(self) -> None:
        self._buffer = b""
        self._data: list[str] = []

    def feed(self, raw: bytes) -> list[str]:
        self._buffer += raw
        payloads: list[str] = []
        while True:
            index = self._buffer.find(b"\n")
            if index < 0:
                return payloads
            line = self._buffer[:index].rstrip(b"\r").decode("utf-8")
            self._buffer = self._buffer[index + 1 :]
            payload = self._line(line)
            if payload is not None:
                payloads.append(payload)

    def flush(self) -> list[str]:
        """Dispatch whatever is left when the connection closes."""
        payloads: list[str] = []
        if self._buffer:
            payload = self._line(self._buffer.rstrip(b"\r").decode("utf-8"))
            self._buffer = b""
            if payload is not None:
                payloads.append(payload)
        payload = self._line("")
        if payload is not None:
            payloads.append(payload)
        return payloads

    def _line(self, line: str) -> str | None:
        if line == "":
            if not self._data:
                return None
            payload = "\n".join(self._data)
            self._data = []
            return payload
        if line.startswith(":"):
            return None
        name, _, value = line.partition(":")
        if name == "data":
            self._data.append(value[1:] if value.startswith(" ") else value)
        return None  # event, id and retry fields carry nothing the harness uses


@dataclass
class StreamOutcome:
    """What a stream reported besides its deltas, filled in while it is read."""

    response_id: str | None = None
    finish_reason: str | None = None
    usage: Usage | None = None
    running_usage: Usage | None = None
    done: bool = False
    usage_after_finish: Usage | None = None

    def final_usage(self) -> Usage | None:
        """The usage to charge: from the `choices: []` chunk, or, when the stream ended
        with [DONE] and no such chunk came, usage sent on or after the finish chunk."""
        if self.usage is not None:
            return self.usage
        if self.done:
            return self.usage_after_finish
        return None


class ChunkNormalizer:
    """Turns JSON payloads into `TextDelta` / `ReasoningDelta` and fills a `StreamOutcome`."""

    def __init__(self, reasoning_fields: Sequence[str]) -> None:
        self._reasoning_fields = tuple(reasoning_fields)
        self.outcome = StreamOutcome()

    def feed(self, payload: str) -> list[TextDelta | ReasoningDelta]:
        if payload.strip() == DONE:
            self.outcome.done = True
            return []
        try:
            chunk: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError:
            raise ApiError("protocol", f"chunk is not JSON: {payload[:200]!r}") from None
        if not isinstance(chunk, dict):
            raise ApiError("protocol", f"chunk is not an object: {payload[:200]!r}")
        if "error" in chunk:
            # Not observed so far; the shape is UNVERIFIED. An OpenAI-style error object
            # may carry an HTTP-like status code.
            error = chunk["error"] if isinstance(chunk["error"], dict) else {}
            code = error.get("code")
            kind = classify_status(code) if isinstance(code, int) else "server"
            message = str(error.get("message") or chunk["error"])[:500]
            raise ApiError(kind, f"error in stream: {message}")
        outcome = self.outcome
        outcome.response_id = outcome.response_id or chunk.get("id")
        choices = chunk.get("choices")
        events: list[TextDelta | ReasoningDelta] = []
        for choice in choices or []:
            if choice.get("index", 0) != 0:
                continue  # the harness never asks for n > 1
            delta = choice.get("delta") or {}
            for name in self._reasoning_fields:
                text = delta.get(name)
                if isinstance(text, str) and text:
                    events.append(ReasoningDelta(text=text))
                    break
            content = delta.get("content")
            if isinstance(content, str) and content:
                events.append(TextDelta(text=content))
            if choice.get("finish_reason") is not None:
                outcome.finish_reason = choice["finish_reason"]
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            parsed = parse_usage(usage)
            if choices == []:
                outcome.usage = parsed
            else:
                outcome.running_usage = parsed
                if outcome.finish_reason is not None:
                    outcome.usage_after_finish = parsed
        return events
