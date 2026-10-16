"""The model harness: the only code in Rookwise that calls the model API.

Public surface so far: `load_config` and `HarnessConfig` (config/harness.json),
`ChatRequest`, `JsonSchemaFormat` and `build_request` (the exact request body), the
normalized event types, `RateLimiter` and `Clock` (requests and tokens per minute plus
a concurrency cap), and `RetryPolicy` with the error taxonomy (`HarnessError`,
`ApiError`, `StreamInterrupted`). The streaming client comes in a later module.
"""

from rookwise.harness.config import ConfigError, HarnessConfig, load_config
from rookwise.harness.events import (
    ErrorEvent,
    Event,
    Finish,
    ReasoningDelta,
    StreamStart,
    TextDelta,
    UsageEvent,
)
from rookwise.harness.ratelimit import Clock, RateLimiter
from rookwise.harness.request import ChatRequest, JsonSchemaFormat, RequestError, build_request
from rookwise.harness.retry import ApiError, HarnessError, RetryPolicy, StreamInterrupted

__all__ = [
    "ApiError",
    "ChatRequest",
    "Clock",
    "ConfigError",
    "ErrorEvent",
    "Event",
    "Finish",
    "HarnessConfig",
    "HarnessError",
    "JsonSchemaFormat",
    "RateLimiter",
    "ReasoningDelta",
    "RequestError",
    "RetryPolicy",
    "StreamInterrupted",
    "StreamStart",
    "TextDelta",
    "UsageEvent",
    "build_request",
    "load_config",
]
