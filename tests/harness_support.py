"""Fakes shared by the harness tests: SSE chunks shaped like the streaming probe saw them,
a mock HTTP transport, a fake clock and a ledger with the real prices. No network."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from rookwise.harness.config import HarnessConfig, load_config
from rookwise.harness.request import ChatRequest
from rookwise.ledger import Caps, InMemoryLedger

TEST_KEY = "test-key-not-a-secret"
LIGHTNING = "nemotron-3.5-lightning"
ULTRA = "nemotron-3-ultra"


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class FakeClock:
    """Time only moves when someone sleeps; every sleep is recorded."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        await asyncio.sleep(0)


def config(env: dict[str, str] | None = None) -> HarnessConfig:
    return load_config(env=env or {})


def ledger(run_usd: float = 1.0, run_id: str = "r-1") -> InMemoryLedger:
    book = InMemoryLedger()
    book.open_run(run_id, Caps(run_usd=run_usd))
    return book


def request(**overrides: Any) -> ChatRequest:
    fields: dict[str, Any] = {
        "model": LIGHTNING,
        "messages": [{"role": "user", "content": "Count from 1 to 3."}],
        "run_id": "r-1",
        "level": "operator",
        "task_id": "t-1",
        "max_tokens": 64,
    }
    fields.update(overrides)
    return ChatRequest(**fields)


# -- chunks, in the shapes observed by scripts/stream_probe.py -------------------------


def chunk(choices: list[dict[str, Any]] | None, usage: dict[str, Any] | None = None) -> str:
    body: dict[str, Any] = {"id": "chatcmpl-test", "object": "chat.completion.chunk"}
    body["choices"] = choices if choices is not None else []
    if usage is not None:
        body["usage"] = usage
    return json.dumps(body)


def role() -> str:
    return chunk([{"index": 0, "delta": {"role": "assistant", "content": ""}}])


def content(text: str) -> str:
    return chunk([{"index": 0, "delta": {"content": text}}])


def reasoning(text: str, fields: Iterable[str] = ("reasoning", "reasoning_content")) -> str:
    return chunk([{"index": 0, "delta": {name: text for name in fields}}])


def finish(reason: str = "stop") -> str:
    return chunk([{"index": 0, "delta": {}, "finish_reason": reason}])


def usage(
    prompt: int = 35,
    completion: int = 21,
    cached: int | None = None,
    reasoning_tokens: int | None = None,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }
    if cached is not None:
        raw["prompt_tokens_details"] = {"cached_tokens": cached}
    if reasoning_tokens is not None:
        raw["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return raw


def final_usage(**kwargs: Any) -> str:
    return chunk([], usage(**kwargs))


def sse(payloads: Iterable[str], done: bool = True) -> bytes:
    text = "".join(f"data: {p}\n\n" for p in payloads)
    if done:
        text += "data: [DONE]\n\n"
    return text.encode("utf-8")


def ok_stream(text: str = "1 2 3", **usage_kwargs: Any) -> bytes:
    return sse([role(), content(text), finish(), final_usage(**usage_kwargs)])


# -- transport -------------------------------------------------------------------------


@dataclass
class Handler:
    """Answers each request with the next response factory in `responses`."""

    responses: list[Callable[[httpx.Request], httpx.Response]]
    requests: list[httpx.Request] = field(default_factory=list)
    bodies: list[dict[str, Any]] = field(default_factory=list)
    active: int = 0
    max_active: int = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        self.bodies.append(json.loads(req.content))
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)(req)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def respond(body: bytes, status: int = 200, headers: dict[str, str] | None = None):
    def make(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, content=body, headers={"content-type": "text/event-stream", **(headers or {})}
        )

    return make


def respond_parts(parts: Iterable[bytes]):
    """A 200 response whose body arrives in the given pieces (split anywhere)."""

    def make(_: httpx.Request) -> httpx.Response:
        async def body() -> AsyncIterator[bytes]:
            for part in parts:
                yield part
                await asyncio.sleep(0)

        return httpx.Response(200, content=body())

    return make


@dataclass
class HangingStream:
    """A 200 response that sends `head` and then never ends, recording when it is closed."""

    head: bytes
    closed: bool = False
    sent: asyncio.Event | None = None

    def __call__(self, _: httpx.Request) -> httpx.Response:
        self.sent = asyncio.Event()

        async def body() -> AsyncIterator[bytes]:
            try:
                yield self.head
                assert self.sent is not None
                self.sent.set()
                await asyncio.Event().wait()
                yield b""  # pragma: no cover
            finally:
                self.closed = True

        return httpx.Response(200, content=body())


def broken_after(head: bytes):
    """A 200 response that sends `head` and then fails with a read error."""

    def make(_: httpx.Request) -> httpx.Response:
        async def body() -> AsyncIterator[bytes]:
            yield head
            raise httpx.ReadError("connection reset")

        return httpx.Response(200, content=body())

    return make


def fails_to_connect(_: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused")
