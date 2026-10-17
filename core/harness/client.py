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
import dataclasses
import os
import random
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

from rookwise.harness.cassette import Cassette, request_key
from rookwise.harness.config import HarnessConfig, load_config
from rookwise.harness.cost import estimate_usage_from_text, full_reservation_usage
from rookwise.harness.events import (
    EVENT_ADAPTER,
    ErrorEvent,
    Event,
    Finish,
    ReasoningDelta,
    StreamStart,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    UsageEvent,
    assemble_tool_calls,
)
from rookwise.harness.ratelimit import Clock, Permit, RateLimiter, SystemClock
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
from rookwise.money import ZERO_USD

_ERROR_BODY_CHARS = 500


def _recorded_error(error: dict[str, Any]) -> ApiError:
    return ApiError(
        error["kind"],
        error["message"],
        status_code=error["status_code"],
        retry_after_s=error["retry_after_s"],
    )


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
    usd: Decimal
    cancelled: bool
    attempts: int
    events: tuple[Event, ...]
    tool_calls: tuple[ToolCall, ...] = ()


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
class _Call:
    """A call's cassette slot: request key and sequence index, and in replay the recording."""

    key: str
    index: int
    recording: dict[str, Any] | None = None


class _NoPermit:
    """Replay makes no API calls, so it takes no rate-limit budget."""

    def release(self, used_tokens: int | None = None) -> None:
        pass


@dataclass(frozen=True)
class _Settlement:
    usage: Usage
    estimated: bool
    usd: Decimal


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
        cassette: Cassette | None = None,
    ) -> None:
        self._ledger = ledger
        self._config = config or load_config()
        self._clock = clock or SystemClock()
        self._rng = rng or random.Random()
        self._policy = RetryPolicy.from_config(self._config.retry)
        self._limiter = limiter or RateLimiter.from_config(self._config, self._clock)
        self._mode = cassette.mode if cassette is not None else self._config.mode
        key = api_key if api_key is not None else os.environ.get("NEBIUS_API_KEY", "")
        key = key.strip()
        if self._mode != "replay" and not key:
            raise HarnessError("NEBIUS_API_KEY is not set")
        if cassette is None and self._mode != "live":
            cassette = Cassette(self._config.cassette_dir / "default.json", self._mode)
        self._cassette = cassette
        if cassette is not None:
            cassette.add_secret(key)
        # Replay never calls the API, so it gets no HTTP client at all.
        self._http = (
            None
            if self._mode == "replay"
            else httpx.AsyncClient(
                base_url=self._config.base_url,
                headers={"Authorization": f"Bearer {key}"},
                timeout=httpx.Timeout(
                    self._config.read_timeout_s, connect=self._config.connect_timeout_s
                ),
                transport=transport,
            )
        )

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def config(self) -> HarnessConfig:
        return self._config

    @property
    def ledger(self) -> Ledger:
        return self._ledger

    @property
    def cassette(self) -> Cassette | None:
        return self._cassette

    async def aclose(self) -> None:
        if self._http is not None:
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
            tool_calls=assemble_tool_calls(e for e in events if isinstance(e, ToolCallDelta)),
        )

    async def stream(
        self, request: ChatRequest, cancel: CancelHandle | None = None
    ) -> AsyncIterator[Event]:
        built = build_request(request, self._config)
        cancel = cancel or CancelHandle()
        call = None
        if self._cassette is not None:
            key = request_key(built.body)
            index = self._cassette.next_index(key)
            recording = self._cassette.lookup(key, index) if self._mode == "replay" else None
            call = _Call(key, index, recording)
        attempt = 0
        while True:
            attempt += 1
            if cancel.cancelled:
                yield Finish(
                    finish_reason=None, usd=ZERO_USD, usage_estimated=False, cancelled=True
                )
                return
            permit: Permit | _NoPermit = _NoPermit()
            if self._mode != "replay":
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
                async with aclosing(self._run_attempt(built, state, cancel, call)) as events:
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
            instant_replay = self._mode == "replay" and not self._cassette.realtime
            if delay > 0 and not instant_replay:
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
            budget_id=request.budget_id,
        )

    async def _run_attempt(
        self, built: BuiltRequest, state: _Attempt, cancel: CancelHandle, call: _Call | None
    ) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        producer = asyncio.create_task(self._produce(self._source(built, state, call), queue))

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
                    if isinstance(item, ToolCallDelta):
                        state.text.append(item.arguments)  # only feeds the output estimate
                    else:
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

    def _source(
        self, built: BuiltRequest, state: _Attempt, call: _Call | None
    ) -> AsyncIterator[Any]:
        if self._mode == "replay":
            assert call is not None and call.recording is not None
            return self._replay_source(state, call.recording)
        source = self._live_source(built, state)
        if self._mode == "record":
            assert call is not None
            return self._record(source, built, state, call)
        return source

    async def _live_source(self, built: BuiltRequest, state: _Attempt) -> AsyncIterator[Any]:
        """POST the request and yield `_STARTED`, then deltas."""
        assert self._http is not None
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

    async def _record(
        self, source: AsyncIterator[Any], built: BuiltRequest, state: _Attempt, call: _Call
    ) -> AsyncIterator[Any]:
        """Pass the live source through and store what it produced in the cassette."""
        assert self._cassette is not None
        start = self._clock.now()
        events: list[dict[str, Any]] = []
        status, error = "ok", None
        try:
            async for item in source:
                if isinstance(item, TextDelta | ReasoningDelta | ToolCallDelta):
                    events.append({**item.model_dump(), "t": round(self._clock.now() - start, 3)})
                yield item
        except ApiError as failure:
            status = "error"
            error = {
                "kind": failure.kind,
                "message": failure.message,
                "status_code": failure.status_code,
                "retry_after_s": failure.retry_after_s,
                "after_start": state.started,
            }
            raise
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        finally:
            outcome = state.outcome
            final = outcome.final_usage()
            running = outcome.running_usage
            self._cassette.put(
                {
                    "key": call.key,
                    "index": call.index,
                    "request": built.body,
                    "status": status,
                    "error": error,
                    "response_id": outcome.response_id,
                    "finish_reason": outcome.finish_reason,
                    "done": outcome.done,
                    "usage": dataclasses.asdict(final) if final else None,
                    "running_usage": dataclasses.asdict(running) if running else None,
                    "events": events,
                }
            )

    async def _replay_source(
        self, state: _Attempt, recording: dict[str, Any]
    ) -> AsyncIterator[Any]:
        """Yield a recorded attempt the way the live source produced it. No network."""
        assert self._cassette is not None
        state.in_flight = True
        error = recording["error"]
        if error is not None and not error["after_start"]:
            raise _recorded_error(error)
        state.started = True
        yield _STARTED
        previous = 0.0
        for raw in recording["events"]:
            if self._cassette.realtime and raw["t"] > previous:
                await self._clock.sleep(raw["t"] - previous)
                previous = raw["t"]
            yield EVENT_ADAPTER.validate_python({k: v for k, v in raw.items() if k != "t"})
        outcome = state.outcome
        outcome.response_id = recording["response_id"]
        outcome.finish_reason = recording["finish_reason"]
        outcome.done = recording["done"]
        outcome.usage = Usage(**recording["usage"]) if recording["usage"] else None
        running = recording["running_usage"]
        outcome.running_usage = Usage(**running) if running else None
        if error is not None:
            raise _recorded_error(error)
        if recording["status"] == "cancelled":
            raise asyncio.CancelledError  # ends the attempt as cancelled, as when recorded

    def _settle(self, built: BuiltRequest, state: _Attempt) -> _Settlement:
        """Charge or release the attempt's reservation, exactly once."""
        state.settled = True
        final = state.outcome.final_usage()
        if final is not None:
            entry = self._ledger.charge(state.reservation, final)
            return _Settlement(final, False, entry.usd_real)
        if state.rejected or not state.in_flight:
            self._ledger.release(state.reservation)
            return _Settlement(Usage(0, 0), False, ZERO_USD)
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
        entry = self._ledger.charge(state.reservation, usage, usage_estimated=True)
        return _Settlement(usage, True, entry.usd_real)
