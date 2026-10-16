"""Per-model token buckets for requests and tokens per minute, plus a concurrency cap.

Limits come from config/rate_limits.json; the cap is `max_concurrent_requests` in
config/harness.json. A call takes one request and its worst-case tokens (input
estimate plus `max_tokens`) before its reservation; when the real usage is known,
`Permit.release(used_tokens)` gives the unused tokens back. UNVERIFIED: whether the
server's token limit counts input plus output tokens, and whether limits are
independent per model; this limiter assumes both.

Each bucket holds at most one minute of budget and refills continuously. The clock is
injectable, so tests run without real sleeping. Every limiter owns its own state.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Protocol

from rookwise.harness.config import HarnessConfig, ModelLimit


class Clock(Protocol):
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class TokenBucket:
    def __init__(self, per_minute: int, now: float) -> None:
        if per_minute <= 0:
            raise ValueError("a limit must be positive")
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.level = self.capacity
        self.updated = now

    def refill(self, now: float) -> None:
        self.level = min(self.capacity, self.level + (now - self.updated) * self.rate)
        self.updated = now

    def wait_for(self, amount: float) -> float:
        """Seconds until `amount` is available (0 if it is now). Call `refill` first."""
        missing = amount - self.level
        return 0.0 if missing <= 0 else missing / self.rate

    def give_back(self, amount: float) -> None:
        self.level = min(self.capacity, self.level + amount)


class Permit:
    """One admitted call: holds a concurrency slot until released."""

    def __init__(self, limiter: RateLimiter, model: str, tokens: int) -> None:
        self._limiter = limiter
        self.model = model
        self.tokens = tokens
        self._released = False

    def release(self, used_tokens: int | None = None) -> None:
        """Free the slot. With `used_tokens`, return the unused part of the token debit."""
        if self._released:
            return
        self._released = True
        if used_tokens is not None and used_tokens < self.tokens:
            self._limiter._give_back(self.model, self.tokens - used_tokens)
        self._limiter._slots.release()


class RateLimiter:
    def __init__(
        self,
        limits: Mapping[str, ModelLimit],
        max_concurrent_requests: int,
        clock: Clock | None = None,
    ) -> None:
        if max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be at least 1")
        self._clock = clock or SystemClock()
        now = self._clock.now()
        self._buckets = {
            model: (
                TokenBucket(limit.requests_per_minute, now),
                TokenBucket(limit.tokens_per_minute, now),
            )
            for model, limit in limits.items()
        }
        self._locks = {model: asyncio.Lock() for model in limits}
        self._slots = asyncio.Semaphore(max_concurrent_requests)
        self.max_concurrent_requests = max_concurrent_requests

    @classmethod
    def from_config(cls, config: HarnessConfig, clock: Clock | None = None) -> RateLimiter:
        return cls(config.limits, config.max_concurrent_requests, clock)

    async def acquire(self, model: str, tokens: int) -> Permit:
        """Wait until the model has a request and `tokens` free, then a concurrency slot."""
        try:
            requests, token_bucket = self._buckets[model]
        except KeyError:
            raise KeyError(f"no rate limit for model {model} in config/rate_limits.json") from None
        if tokens > token_bucket.capacity:
            raise ValueError(
                f"{tokens} tokens can never fit {model}'s limit of "
                f"{int(token_bucket.capacity)} tokens per minute"
            )
        while True:
            async with self._locks[model]:
                now = self._clock.now()
                requests.refill(now)
                token_bucket.refill(now)
                wait = max(requests.wait_for(1), token_bucket.wait_for(tokens))
                if wait <= 0:
                    requests.level -= 1
                    token_bucket.level -= tokens
                    break
            await self._clock.sleep(wait)
        await self._slots.acquire()
        return Permit(self, model, tokens)

    def available(self, model: str) -> tuple[float, float]:
        """Requests and tokens available now, for tests and monitoring."""
        requests, tokens = self._buckets[model]
        now = self._clock.now()
        requests.refill(now)
        tokens.refill(now)
        return requests.level, tokens.level

    def _give_back(self, model: str, tokens: int) -> None:
        self._buckets[model][1].give_back(tokens)
