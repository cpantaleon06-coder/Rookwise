"""Token buckets with an injected clock, the concurrency cap, and the retry policy."""

import asyncio
import random
from datetime import UTC, datetime

import pytest
from harness_support import FakeClock, run

from rookwise.harness.config import ModelLimit
from rookwise.harness.ratelimit import RateLimiter
from rookwise.harness.retry import (
    ApiError,
    RetryPolicy,
    StreamInterrupted,
    classify_status,
    parse_retry_after,
)

MODEL = "m"


def _limiter(rpm=600, tpm=1_000_000, concurrency=8, clock=None):
    return RateLimiter({MODEL: ModelLimit(rpm, tpm)}, concurrency, clock or FakeClock())


def test_requests_per_minute_are_enforced():
    async def main():
        clock = FakeClock()
        limiter = _limiter(rpm=2, clock=clock)
        for _ in range(2):
            (await limiter.acquire(MODEL, 1)).release()
        assert clock.sleeps == []
        (await limiter.acquire(MODEL, 1)).release()
        # 2 per minute refill one request every 30 seconds.
        assert clock.sleeps == [pytest.approx(30.0)]

    run(main())


def test_tokens_per_minute_are_enforced_and_unused_tokens_come_back():
    async def main():
        clock = FakeClock()
        limiter = _limiter(tpm=6_000, clock=clock)
        permit = await limiter.acquire(MODEL, 5_000)
        permit.release(used_tokens=1_000)  # 4,000 come back
        assert limiter.available(MODEL)[1] == pytest.approx(5_000)
        (await limiter.acquire(MODEL, 5_000)).release()
        assert clock.sleeps == []
        (await limiter.acquire(MODEL, 2_000)).release()
        # 0 left, 100 tokens per second refill: 20 seconds for 2,000.
        assert sum(clock.sleeps) == pytest.approx(20.0)

    run(main())


def test_a_call_bigger_than_the_minute_budget_is_refused():
    async def main():
        with pytest.raises(ValueError, match="never fit"):
            await _limiter(tpm=100).acquire(MODEL, 101)
        with pytest.raises(KeyError):
            await _limiter().acquire("unknown", 1)

    run(main())


def test_concurrency_cap_holds_extra_calls_until_a_slot_frees():
    async def main():
        limiter = _limiter(concurrency=1)
        first = await limiter.acquire(MODEL, 1)
        second = asyncio.create_task(limiter.acquire(MODEL, 1))
        await asyncio.sleep(0)
        assert not second.done()
        first.release()
        (await second).release()

    run(main())


def test_status_classification():
    assert classify_status(429) == "rate_limited"
    assert classify_status(408) == "timeout"
    assert classify_status(503) == "server"
    assert classify_status(422) == "validation"
    assert classify_status(401) == "auth"
    assert classify_status(404) == "not_found"
    assert classify_status(409) == "client"


def test_retry_after_seconds_and_http_date():
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after(None) is None and parse_retry_after("soon") is None
    now = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("Fri, 16 Oct 2026 12:00:05 GMT", now) == 5.0


def test_policy_honors_retry_after_backs_off_and_stops():
    policy = RetryPolicy(4, base_delay_s=1.0, max_delay_s=30.0, jitter=0.2, max_retry_after_s=60)
    rng = random.Random(0)
    limited = ApiError("rate_limited", "slow down", status_code=429, retry_after_s=7.0)
    assert policy.delay(1, limited, rng) == 7.0
    too_long = ApiError("rate_limited", "later", status_code=429, retry_after_s=61.0)
    assert policy.delay(1, too_long, rng) is None
    server = ApiError("server", "oops", status_code=503)
    for attempt, base in ((1, 1.0), (2, 2.0), (3, 4.0)):
        assert base * 0.8 <= policy.delay(attempt, server, rng) <= base * 1.2
    assert policy.delay(4, server, rng) is None
    assert policy.delay(1, ApiError("validation", "bad", status_code=422), rng) is None
    assert policy.delay(1, StreamInterrupted("cut"), rng) is None
