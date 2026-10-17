"""Error taxonomy and the bounded retry policy.

Retryable: HTTP 408 (`timeout`), 429 (`rate_limited`), 5xx (`server`), and connection
errors or timeouts before the response headers arrive (`connection`, `timeout`).
Everything else is final, in particular 4xx validation errors such as 422.

Backoff is exponential with jitter: `base * 2^(attempt - 1)`, capped at `max_delay_s`,
times a random factor in `[1 - jitter, 1 + jitter]`. A `Retry-After` header (seconds,
VERIFIED on 429 in the Token Factory docs) replaces the backoff; if it asks for more
than `max_retry_after_s`, the call gives up instead of waiting.

Retries never double-charge: the client gives every attempt its own ledger reservation
and releases it when the attempt fails before the response starts.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime

import httpx

from rookwise.harness.config import RetryConfig
from rookwise.harness.events import ErrorKind
from rookwise.money import ZERO_USD

RETRYABLE: frozenset[ErrorKind] = frozenset({"rate_limited", "timeout", "server", "connection"})


class HarnessError(Exception):
    """Base class for every error the harness raises on purpose."""


class ApiError(HarnessError):
    """A model call failed. `kind` comes from the taxonomy in `events.ErrorKind`."""

    def __init__(
        self,
        kind: ErrorKind,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(
            f"{kind}: {message}"
            if status_code is None
            else f"{kind} (HTTP {status_code}): {message}"
        )
        self.kind: ErrorKind = kind
        self.message = message
        self.status_code = status_code
        self.retry_after_s = retry_after_s

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE


class StreamInterrupted(ApiError):
    """The stream broke after it started. Never retried: output was already delivered.

    The ledger is settled before this is raised; `usd` is what was charged.
    """

    def __init__(
        self, message: str, *, usd: Decimal = ZERO_USD, usage_estimated: bool = True
    ) -> None:
        super().__init__("stream_interrupted", message)
        self.usd = usd
        self.usage_estimated = usage_estimated


def classify_status(status: int) -> ErrorKind:
    if status == 408:
        return "timeout"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server"
    if status in (400, 422):
        return "validation"
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    return "client"


def classify_exception(exc: BaseException) -> ErrorKind:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.TransportError):
        return "connection"
    return "protocol"


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds from a `Retry-After` header: delta-seconds or an HTTP date. None if absent
    or unreadable."""
    if value is None or not value.strip():
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay_s: float
    max_delay_s: float
    jitter: float
    max_retry_after_s: float

    @classmethod
    def from_config(cls, config: RetryConfig) -> RetryPolicy:
        return cls(
            config.max_attempts,
            config.base_delay_s,
            config.max_delay_s,
            config.jitter,
            config.max_retry_after_s,
        )

    def delay(self, attempt: int, error: ApiError, rng: random.Random) -> float | None:
        """Seconds to wait before attempt `attempt + 1`, or None to give up."""
        if not error.retryable or attempt >= self.max_attempts:
            return None
        if error.retry_after_s is not None:
            if error.retry_after_s > self.max_retry_after_s:
                return None
            return error.retry_after_s
        backoff = min(self.max_delay_s, self.base_delay_s * 2 ** (attempt - 1))
        factor = 1 + self.jitter * (2 * rng.random() - 1)
        return min(self.max_delay_s, max(0.0, backoff * factor))
