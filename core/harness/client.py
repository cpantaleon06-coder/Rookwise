"""Streaming client for Token Factory chat completions, gated by the budget ledger.

For every attempt of a call:
1. The rate limiter admits it (one request, worst-case tokens, a concurrency slot).
2. The ledger reserves the worst case (input estimate plus `max_tokens` at the model's
   price). A reservation that does not fit raises `CapReached` and nothing is sent.
3. The request streams. The reservation is then settled exactly once:
   - final usage received: charge it (the ledger releases the rest of the hold);
   - the server answered with an error status, or the connection failed before the
     response started: release it, and retry if the error is retryable;
   - the stream started but ended, broke or was cancelled without final usage: charge
     according to `on_missing_usage` (config/harness.json) and mark the usage estimated.
     A request that was sent but cancelled before the response started is charged the
     same way, since the server may already be working on it.
   A call cancelled before its request is sent is released.

Cancellation: cancel the consuming task (asyncio), or pass a `CancelHandle` and call
`cancel()`. Either way the HTTP connection is closed and the ledger is settled. After
a handle cancel the stream ends with `Finish(cancelled=True)`; an asyncio cancellation
propagates `CancelledError`. Consumers that stop iterating early should close the
stream, for example with `contextlib.aclosing`, so settlement runs at once.
"""

from __future__ import annotations

import asyncio
import os
import random
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Any

import httpx

from rookwise.harness.config import HarnessConfig, load_config
from rookwise.harness.cost import estimate_usage_from_text, full_reservation_usage
from rookwise.harness.events import (
    ErrorEvent,
    Event,
    Finish,
    ReasoningDelta,
    StreamStart,
    TextDelta,
    UsageEvent,
)
from rookwise.harness.ratelimit import Clock, RateLimiter, SystemClock
from rookwise.harness.request import BuiltRequest, ChatRequest, build_request
from rookwise.harness.retry import (
    ApiError,
    HarnessError,
    RetryPolicy,
    StreamInterrupted,
    classify_exception,
    classify_status,
    parse_retry_after,
)
from rookwise.harness.sse import ChunkNormalizer, SSEDecoder, StreamOutcome
from rookwise.ledger import Ledger, Reservation, Usage

_ERROR_BODY_CHARS = 500


class CancelHandle:
    """Cancels a running call from outside the task that consumes it."""

    def __init__(self) -> None:
        self._cancelled = False
        self._callbacks: list[Callable[[], Any]] = []

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        for callback in list(self._callbacks):
            callback()

    def _subscribe(self, callback: Callable[[], Any]) -> Callable[[], None]:
        self._callbacks.append(callback)
        return lambda: self._callbacks.remove(callback)


@dataclass(frozen=True)
class Result:
    """A finished call, from `Harness.complete`."""

    text: str
    reasoning: str
    finish_reason: str | None
    usage: Usage
    usage_estimated: bool
    usd: float
    cancelled: bool
    attempts: int
    events: tuple[Event, ...]


class _Marker:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return self.name


_STARTED = _Marker("STARTED")
_END = _Marker("END")
_CANCELLED = _Marker("CANCELLED")


@dataclass
class _Failure:
    error: BaseException


@dataclass
class _Attempt:
    """State of one attempt; it decides how the reservation is settled."""

    number: int
    reservation: Reservation
    outcome: StreamOutcome = field(default_factory=StreamOutcome)
    in_flight: bool = False  # the request may have reached the server
    started: bool = False  # HTTP 200 received
    rejected: bool = False  # error status or connection failure before the start
    cancelled: bool = False
    settled: bool = False
    text: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Settlement:
    usage: Usage
    estimated: bool
    usd: float


class Harness:
    """Holds the HTTP client, rate limiter and retry policy for one ledger.

    Several harnesses can run in one process; none of them shares mutable state.
    """

    def __init__(
        self,
        ledger: Ledger,
        *,
        config: HarnessConfig | None = None,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: RateLimiter | None = None,
        clock: Clock | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._ledger = ledger
        self._config = config or load_config()
        self._clock = clock or SystemClock()
        self._rng = rng or random.Random()
        self._policy = RetryPolicy.from_config(self._config.retry)
        self._limiter = limiter or RateLimiter.from_config(self._config, self._clock)
        key = api_key if api_key is not None else os.environ.get("NEBIUS_API_KEY", "")
        if not key.strip():
            raise HarnessError("NEBIUS_API_KEY is not set")
        self._http = httpx.AsyncClient(
            base_url=self._config.base_url,
            headers={"Authorization": f"Bearer {key.strip()}"},
            timeout=httpx.Timeout(
                self._config.read_timeout_s, connect=self._config.connect_timeout_s
            ),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Harness:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def complete(self, request: ChatRequest, cancel: CancelHandle | None = None) -> Result:
        """Run a call to the end and collect it. Errors propagate after settlement."""
        events: list[Event] = []
        async with aclosing(self.stream(request, cancel)) as stream:
            async for event in stream:
                events.append(event)
        finish = next(e for e in reversed(events) if isinstance(e, Finish))
        usage = next((e for e in reversed(events) if isinstance(e, UsageEvent)), None)
        attempts = [e.attempt for e in events if isinstance(e, StreamStart | ErrorEvent)]
        return Result(
            text="".join(e.text for e in events if isinstance(e, TextDelta)),
            reasoning="".join(e.text for e in events if isinstance(e, ReasoningDelta)),
            finish_reason=finish.finish_reason,
            usage=Usage(
                usage.input_tokens,
                usage.output_tokens,
                usage.cached_tokens,
                usage.reasoning_tokens,
            )
            if usage
            else Usage(0, 0),
            usage_estimated=finish.usage_estimated,
            usd=finish.usd,
            cancelled=finish.cancelled,
            attempts=max(attempts, default=0),
            events=tuple(events),
        )

    async def stream(
        self, request: ChatRequest, cancel: CancelHandle | None = None
    ) -> AsyncIterator[Event]:
        built = build_request(request, self._config)
        cancel = cancel or CancelHandle()
        attempt = 0
        while True:
            attempt += 1
            if cancel.cancelled:
                yield Finish(finish_reason=None, usd=0.0, usage_estimated=False, cancelled=True)
                return
            permit = await self._limiter.acquire(built.model.alias, built.worst_case_tokens)
            used_tokens: int | None = None
            try:
                reservation = self._reserve(built)
            except BaseException:
                permit.release(used_tokens=0)
                raise
            state = _Attempt(attempt, reservation)
            try:
                # aclosing: if our consumer stops early, the attempt settles right away.
                async with aclosing(self._run_attempt(built, state, cancel)) as events:
                    async for event in events:
                        if isinstance(event, UsageEvent) and not event.estimated:
                            used_tokens = event.input_tokens + event.output_tokens
                        yield event
                return
            except ApiError as error:
                delay = None
                if not state.started and not isinstance(error, StreamInterrupted):
                    delay = self._policy.delay(attempt, error, self._rng)
                yield ErrorEvent(
                    kind=error.kind,
                    message=error.message,
                    status_code=error.status_code,
                    retryable=delay is not None,
                    attempt=attempt,
                )
                if delay is None:
                    raise
            finally:
                permit.release(used_tokens)
            if delay > 0:
                await self._clock.sleep(delay)

    # -- one attempt -------------------------------------------------------------------

    def _reserve(self, built: BuiltRequest) -> Reservation:
        request = built.request
        return self._ledger.reserve(
            request.run_id,
            level=request.level,
            task_id=request.task_id,
            model=built.model.alias,
            input_tokens=built.input_tokens_estimate,
            max_output_tokens=built.max_tokens,
            usd_predicted=request.usd_predicted,
            skills=request.skills,
        )

    async def _run_attempt(
        self, built: BuiltRequest, state: _Attempt, cancel: CancelHandle
    ) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        producer = asyncio.create_task(self._produce(self._source(built, state), queue))

        def on_cancel() -> None:
            # A task cancelled before its first step never runs its body, so the marker
            # is queued here too, or the consumer below would wait forever.
            producer.cancel()
            queue.put_nowait(_CANCELLED)

        unsubscribe = cancel._subscribe(on_cancel)
        try:
            try:
                while True:
                    if cancel.cancelled:
                        state.cancelled = True
                        break
                    item = await queue.get()
                    if item is _END:
                        break
                    if item is _CANCELLED:
                        state.cancelled = True
                        break
                    if isinstance(item, _Failure):
                        raise item.error
                    if item is _STARTED:
                        yield StreamStart(
                            model=built.model.alias,
                            model_id=built.model.model_id,
                            attempt=state.number,
                        )
                        continue
                    (state.text if isinstance(item, TextDelta) else state.reasoning).append(
                        item.text
                    )
                    yield item
            finally:
                unsubscribe()
                if not producer.done():
                    producer.cancel()
                # Wait until the producer has closed the connection.
                await asyncio.gather(producer, return_exceptions=True)
            settlement = self._settle(built, state)
        except ApiError as error:
            if state.started:
                settlement = self._settle(built, state)
                raise StreamInterrupted(
                    error.message, usd=settlement.usd, usage_estimated=settlement.estimated
                ) from error
            state.rejected = True
            self._settle(built, state)
            raise
        finally:
            if not state.settled:  # asyncio cancellation or an unexpected error
                self._settle(built, state)
        usage = settlement.usage
        yield UsageEvent(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cached_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            estimated=settlement.estimated,
        )
        yield Finish(
            finish_reason=state.outcome.finish_reason,
            usd=settlement.usd,
            usage_estimated=settlement.estimated,
            cancelled=state.cancelled,
        )

    @staticmethod
    async def _produce(source: AsyncIterator[Any], queue: asyncio.Queue[Any]) -> None:
        """Reads the source in one task, so the connection opens and closes in it."""
        try:
            async for item in source:
                queue.put_nowait(item)
            queue.put_nowait(_END)
        except asyncio.CancelledError:
            queue.put_nowait(_CANCELLED)
        except BaseException as error:  # handed to the consumer, which raises it
            queue.put_nowait(_Failure(error))
        finally:
            await source.aclose()  # type: ignore[attr-defined]

    async def _source(self, built: BuiltRequest, state: _Attempt) -> AsyncIterator[Any]:
        """Live source: POST the request and yield `_STARTED`, then deltas."""
        normalizer = ChunkNormalizer(built.model.reasoning_fields)
        state.outcome = normalizer.outcome
        decoder = SSEDecoder()
        state.in_flight = True
        try:
            async with self._http.stream("POST", "chat/completions", json=built.body) as response:
                if response.status_code != 200:
                    raw = await response.aread()
                    raise ApiError(
                        classify_status(response.status_code),
                        raw.decode("utf-8", "replace")[:_ERROR_BODY_CHARS],
                        status_code=response.status_code,
                        retry_after_s=parse_retry_after(response.headers.get("retry-after")),
                    )
                state.started = True
                yield _STARTED
                async for raw in response.aiter_bytes():
                    for payload in decoder.feed(raw):
                        for event in normalizer.feed(payload):
                            yield event
                    if normalizer.outcome.done:
                        return
                for payload in decoder.flush():
                    for event in normalizer.feed(payload):
                        yield event
        except httpx.HTTPError as error:
            kind = classify_exception(error)
            raise ApiError(kind, f"{type(error).__name__}: {error}") from error

    def _settle(self, built: BuiltRequest, state: _Attempt) -> _Settlement:
        """Charge or release the attempt's reservation, exactly once."""
        state.settled = True
        final = state.outcome.final_usage()
        if final is not None:
            entry = self._ledger.charge(state.reservation, final)
            return _Settlement(final, False, entry.usd_real)
        if state.rejected or not state.in_flight:
            self._ledger.release(state.reservation)
            return _Settlement(Usage(0, 0), False, 0.0)
        if self._config.on_missing_usage == "estimate_from_text":
            usage = estimate_usage_from_text(
                built.input_tokens_estimate,
                "".join(state.text),
                "".join(state.reasoning),
                self._config.chars_per_token,
                built.max_tokens,
                state.outcome.running_usage,
            )
        else:
            usage = full_reservation_usage(built.input_tokens_estimate, built.max_tokens)
        entry = self._ledger.charge(state.reservation, usage)
        return _Settlement(usage, True, entry.usd_real)
