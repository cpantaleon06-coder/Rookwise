"""The streaming client against a mock transport: events, ledger settlement, cancellation,
retries and caps. No network, no real key, no real sleeping."""

import asyncio
import dataclasses
import math
import random
from contextlib import aclosing
from decimal import ROUND_HALF_EVEN, Decimal

import pytest
from harness_support import (
    TEST_KEY,
    FakeClock,
    Handler,
    HangingStream,
    broken_after,
    config,
    content,
    fails_to_connect,
    final_usage,
    finish,
    ledger,
    ok_stream,
    reasoning,
    request,
    respond,
    respond_parts,
    role,
    run,
    sse,
)

from rookwise.harness import (
    ApiError,
    CancelHandle,
    ErrorEvent,
    Finish,
    Harness,
    HarnessError,
    ReasoningDelta,
    StreamInterrupted,
    StreamStart,
    TextDelta,
    UsageEvent,
    build_request,
)
from rookwise.ledger import CapReached, Usage, call_cost, load_prices

PRICES = load_prices()


def _harness(handler, book, *, cfg=None, clock=None, seed=0):
    return Harness(
        book,
        config=cfg or config(),
        api_key=TEST_KEY,
        transport=handler.transport(),
        clock=clock or FakeClock(),
        rng=random.Random(seed),
    )


def _reservation_usd(req, cfg=None):
    built = build_request(req, cfg or config())
    price = PRICES[built.model.alias]
    return call_cost(price, Usage(built.input_tokens_estimate, built.max_tokens)).usd


def _assert_no_hold(book, run_id="r-1"):
    report = book.report(run_id)
    assert report.held_usd == 0
    return report


def test_success_streams_events_and_charges_real_usage():
    async def main():
        book = ledger()
        handler = Handler([respond(ok_stream("1 2 3", prompt=35, completion=21))])
        async with _harness(handler, book) as harness:
            result = await harness.complete(request(skills=("prose-style",)))
        types = [type(e) for e in result.events]
        assert types == [StreamStart, TextDelta, UsageEvent, Finish]
        assert result.text == "1 2 3" and result.finish_reason == "stop"
        assert result.usage == Usage(35, 21) and not result.usage_estimated
        report = _assert_no_hold(book)
        (entry,) = report.entries
        assert entry.input_tokens == 35 and entry.output_tokens == 21
        assert entry.usage_estimated is False
        assert entry.skills == ["prose-style"]
        assert (
            result.usd
            == entry.usd_real
            == call_cost(PRICES["nemotron-3.5-lightning"], Usage(35, 21)).usd
        )
        sent = handler.requests[0]
        assert sent.headers["authorization"] == f"Bearer {TEST_KEY}"
        assert handler.bodies[0]["stream_options"] == {"include_usage": True}

    run(main())


def test_reasoning_deltas_and_reported_cached_and_reasoning_tokens():
    async def main():
        book = ledger()
        body = sse(
            [
                role(),
                reasoning("think", ("reasoning", "reasoning_content")),
                content("$8"),
                finish(),
                final_usage(prompt=41, completion=135, cached=0, reasoning_tokens=131),
            ]
        )
        async with _harness(Handler([respond(body)]), book) as harness:
            result = await harness.complete(request(reasoning=True))
        assert result.reasoning == "think" and result.text == "$8"
        assert [e for e in result.events if isinstance(e, ReasoningDelta)] == [
            ReasoningDelta(text="think")
        ]
        (entry,) = _assert_no_hold(book).entries
        assert entry.reasoning_tokens == 131 and entry.cached_tokens == 0
        assert entry.cached_price_fallback is True

    run(main())


def test_events_split_across_network_reads():
    async def main():
        body = ok_stream("split me", prompt=10, completion=3)
        parts = [body[i : i + 5] for i in range(0, len(body), 5)]
        async with _harness(Handler([respond_parts(parts)]), ledger()) as harness:
            result = await harness.complete(request())
        assert result.text == "split me" and result.usage == Usage(10, 3)

    run(main())


def test_missing_usage_charges_the_full_reservation_by_default():
    async def main():
        book = ledger()
        body = sse([role(), content("1 2 3"), finish()])
        async with _harness(Handler([respond(body)]), book) as harness:
            result = await harness.complete(request())
        assert result.usage_estimated is True
        assert result.events[-2] == UsageEvent(
            input_tokens=result.usage.input_tokens,
            output_tokens=64,
            estimated=True,
        )
        (entry,) = _assert_no_hold(book).entries
        assert entry.usd_real == result.usd == _reservation_usd(request())
        assert entry.usage_estimated is True

    run(main())


def test_missing_usage_can_be_estimated_from_text_instead():
    async def main():
        book = ledger()
        cfg = dataclasses.replace(config(), on_missing_usage="estimate_from_text")
        body = sse([role(), content("1 2 3"), finish()])
        async with _harness(Handler([respond(body)]), book, cfg=cfg) as harness:
            result = await harness.complete(request())
        assert result.usage_estimated is True
        # 5 characters over the configured characters per token, rounded up.
        assert result.usage.output_tokens == math.ceil(5 / cfg.chars_per_token)
        assert 0 < result.usd < _reservation_usd(request())
        _assert_no_hold(book)

    run(main())


def test_cancel_handle_mid_stream_closes_the_connection_and_settles():
    async def main():
        book = ledger()
        hanging = HangingStream(sse([role(), content("1 2")], done=False))
        cancel = CancelHandle()
        events = []
        async with _harness(Handler([hanging]), book) as harness:
            async with aclosing(harness.stream(request(), cancel)) as stream:
                async for event in stream:
                    events.append(event)
                    if isinstance(event, TextDelta):
                        cancel.cancel()
        assert hanging.closed
        finish_event = events[-1]
        assert isinstance(finish_event, Finish) and finish_event.cancelled
        assert finish_event.usage_estimated is True
        (entry,) = _assert_no_hold(book).entries
        assert entry.usd_real == _reservation_usd(request())

    run(main())


def test_asyncio_cancellation_mid_stream_closes_the_connection_and_settles():
    async def main():
        book = ledger()
        hanging = HangingStream(sse([role(), content("1")], done=False))
        async with _harness(Handler([hanging]), book) as harness:
            task = asyncio.create_task(harness.complete(request()))
            while hanging.sent is None or not hanging.sent.is_set():
                await asyncio.sleep(0)
            for _ in range(5):
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert hanging.closed
        (entry,) = _assert_no_hold(book).entries
        assert entry.usd_real == _reservation_usd(request())

    run(main())


def test_closing_the_stream_early_settles_at_once():
    async def main():
        book = ledger()
        hanging = HangingStream(sse([role(), content("1")], done=False))
        async with _harness(Handler([hanging]), book) as harness:
            async with aclosing(harness.stream(request())) as stream:
                async for event in stream:
                    if isinstance(event, TextDelta):
                        break
            assert hanging.closed
            (entry,) = _assert_no_hold(book).entries
            assert entry.usd_real == _reservation_usd(request())

    run(main())


def test_cancel_right_after_the_attempt_starts_does_not_hang():
    async def main():
        book = ledger()
        handler = Handler([respond(ok_stream("never read"))])
        cancel = CancelHandle()
        async with _harness(handler, book) as harness:
            task = asyncio.create_task(harness.complete(request(), cancel))
            await asyncio.sleep(0)  # the call is now waiting for its first chunk
            cancel.cancel()
            result = await asyncio.wait_for(task, timeout=2)
        assert result.cancelled
        report = _assert_no_hold(book)
        assert sum(e.usd_real for e in report.entries) <= _reservation_usd(request())

    run(main())


def test_cancel_before_the_call_sends_nothing_and_spends_nothing():
    async def main():
        book = ledger()
        handler = Handler([])
        cancel = CancelHandle()
        cancel.cancel()
        async with _harness(handler, book) as harness:
            result = await harness.complete(request(), cancel)
        assert result.cancelled and result.usd == 0 and handler.requests == []
        assert _assert_no_hold(book).entries == ()

    run(main())


def test_429_honors_retry_after_without_double_charging():
    async def main():
        book = ledger()
        clock = FakeClock()
        handler = Handler(
            [
                respond(b'{"detail": "rate limited"}', 429, {"retry-after": "7"}),
                respond(ok_stream("ok", prompt=35, completion=2)),
            ]
        )
        async with _harness(handler, book, clock=clock) as harness:
            result = await harness.complete(request())
        assert clock.sleeps == [7.0]
        errors = [e for e in result.events if isinstance(e, ErrorEvent)]
        assert [(e.kind, e.status_code, e.retryable, e.attempt) for e in errors] == [
            ("rate_limited", 429, True, 1)
        ]
        assert result.attempts == 2 and result.text == "ok"
        (entry,) = _assert_no_hold(book).entries
        assert entry.usd_real == result.usd

    run(main())


def test_retries_stop_at_the_cap_with_backoff():
    async def main():
        book = ledger()
        clock = FakeClock()
        attempts = config().retry.overload_max_attempts  # a 503 is provider overload
        handler = Handler([respond(b"busy", 503) for _ in range(attempts)])
        async with _harness(handler, book, clock=clock) as harness:
            with pytest.raises(ApiError) as caught:
                await harness.complete(request())
        assert caught.value.kind == "server" and caught.value.status_code == 503
        assert len(handler.requests) == attempts
        assert len(clock.sleeps) == attempts - 1
        assert clock.sleeps == sorted(clock.sleeps)
        assert _assert_no_hold(book).entries == ()

    run(main())


def test_connection_errors_are_retried():
    async def main():
        book = ledger()
        handler = Handler([fails_to_connect, respond(ok_stream("ok"))])
        async with _harness(handler, book) as harness:
            result = await harness.complete(request())
        assert result.text == "ok" and len(handler.requests) == 2
        assert len(_assert_no_hold(book).entries) == 1

    run(main())


def test_422_is_never_retried():
    async def main():
        book = ledger()
        clock = FakeClock()
        detail = b'{"detail": [{"type": "missing", "loc": ["body", "x"]}]}'
        handler = Handler([respond(detail, 422)])
        events = []
        async with _harness(handler, book, clock=clock) as harness:
            with pytest.raises(ApiError) as caught:
                async with aclosing(harness.stream(request())) as stream:
                    async for event in stream:
                        events.append(event)
        assert caught.value.kind == "validation" and not caught.value.retryable
        assert len(handler.requests) == 1 and clock.sleeps == []
        assert isinstance(events[-1], ErrorEvent) and events[-1].retryable is False
        assert _assert_no_hold(book).entries == ()

    run(main())


def test_a_stream_broken_after_the_start_is_charged_and_not_retried():
    async def main():
        book = ledger()
        handler = Handler([broken_after(sse([role(), content("1 2")], done=False))])
        async with _harness(handler, book) as harness:
            with pytest.raises(StreamInterrupted) as caught:
                await harness.complete(request())
        assert len(handler.requests) == 1
        (entry,) = _assert_no_hold(book).entries
        assert caught.value.usd == entry.usd_real == _reservation_usd(request())
        assert entry.usage_estimated is True

    run(main())


def test_a_reservation_that_does_not_fit_is_never_sent():
    async def main():
        book = ledger(run_usd=_reservation_usd(request()) / 2)
        handler = Handler([])
        async with _harness(handler, book) as harness:
            with pytest.raises(CapReached):
                await harness.complete(request())
        assert handler.requests == []
        assert _assert_no_hold(book).entries == ()

    run(main())


def test_a_call_with_a_budget_id_is_drawn_from_that_allocation():
    async def main():
        book = ledger()
        allocation = book.allocate("r-1", "op-1", Decimal("0.01"))
        handler = Handler([respond(ok_stream())])
        async with _harness(handler, book) as harness:
            result = await harness.complete(request(budget_id="op-1"))
        report = _assert_no_hold(book)
        (node,) = report.allocations
        assert node.spent_usd == result.usd == report.spent_usd > 0
        assert book.free("r-1", "op-1") == allocation.usd - result.usd
        assert book.free("r-1") == Decimal("1") - allocation.usd
        assert "budget_id" not in handler.bodies[0]  # ledger-only, never sent

    run(main())


def test_a_call_that_does_not_fit_its_allocation_is_never_sent():
    async def main():
        book = ledger()
        book.allocate("r-1", "op-1", _reservation_usd(request()) / 2)
        handler = Handler([])
        async with _harness(handler, book) as harness:
            with pytest.raises(CapReached) as refused:
                await harness.complete(request(budget_id="op-1"))
        assert (refused.value.scope, refused.value.key) == ("budget", "op-1")
        assert handler.requests == [] and _assert_no_hold(book).entries == ()

    run(main())


def test_reservations_never_pass_the_cap_under_concurrency():
    async def main():
        one = _reservation_usd(request())
        book = ledger(run_usd=one * Decimal("2.5"))
        first = HangingStream(sse([role(), content("a")], done=False))
        second = HangingStream(sse([role(), content("b")], done=False))
        handler = Handler([first, second])
        async with _harness(handler, book) as harness:
            tasks = [asyncio.create_task(harness.complete(request())) for _ in range(2)]
            while not (first.sent and first.sent.is_set() and second.sent and second.sent.is_set()):
                await asyncio.sleep(0)
            assert book.report("r-1").held_usd == 2 * one
            with pytest.raises(CapReached):
                await harness.complete(request())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        report = _assert_no_hold(book)
        assert len(report.entries) == 2 and len(handler.requests) == 2

    run(main())


def test_concurrency_cap_limits_requests_in_flight():
    async def main():
        cfg = dataclasses.replace(config(), max_concurrent_requests=1)
        book = ledger()
        first = HangingStream(sse([role(), content("a")], done=False))
        handler = Handler([first, respond(ok_stream("b"))])
        cancel = CancelHandle()
        async with _harness(handler, book, cfg=cfg) as harness:
            one = asyncio.create_task(harness.complete(request(), cancel))
            while first.sent is None or not first.sent.is_set():
                await asyncio.sleep(0)
            two = asyncio.create_task(harness.complete(request()))
            for _ in range(20):
                await asyncio.sleep(0)
            assert len(handler.requests) == 1  # the second call waits for the slot
            cancel.cancel()
            first_result, second_result = await asyncio.gather(one, two)
        assert first_result.cancelled and second_result.text == "b"
        assert len(handler.requests) == 2
        assert len(_assert_no_hold(book).entries) == 2


def test_a_missing_key_is_refused_before_any_call(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    with pytest.raises(HarnessError, match="NEBIUS_API_KEY"):
        Harness(ledger(), config=config())


def test_native_tool_calls_stream_and_assemble():
    async def main():
        from harness_support import tool_call

        book = ledger()
        body = sse(
            [
                role(),
                content("I need the add tool."),
                tool_call(id="call_9", name="add", arguments='{"a": '),
                tool_call(arguments="1}"),
                finish("tool_calls"),
                final_usage(prompt=300, completion=30),
            ]
        )
        async with _harness(Handler([respond(body)]), book) as harness:
            result = await harness.complete(request())
        assert result.finish_reason == "tool_calls"
        assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [
            ("call_9", "add", '{"a": 1}')
        ]
        assert result.text == "I need the add tool."
        _assert_no_hold(book)

    run(main())


def test_every_call_records_the_harness_prediction_next_to_its_real_cost():
    async def main():
        book = ledger()
        handler = Handler([respond(ok_stream("1 2 3", prompt=35, completion=21))])
        req = request(max_tokens=64)
        async with _harness(handler, book) as harness:
            await harness.complete(req)
        built = build_request(req, config())
        cfg = config()
        assert built.predicted_input_tokens < built.input_tokens_estimate  # no headroom
        assert built.predicted_output_tokens == math.ceil(64 * cfg.prediction_output_fraction)
        expected = Usage(built.predicted_input_tokens, built.predicted_output_tokens)
        exact = call_cost(PRICES["nemotron-3.5-lightning"], expected).usd_exact
        (entry,) = _assert_no_hold(book).entries
        assert entry.usd_predicted == exact.quantize(Decimal("0.000001"), ROUND_HALF_EVEN)
        assert entry.usd_predicted > 0
        assert book.report("r-1").predicted_usd == entry.usd_predicted

    run(main())
