"""The model harness: the only code in Rookwise that calls the model API.

Public surface so far: `load_config` and `HarnessConfig` (config/harness.json),
`ChatRequest`, `JsonSchemaFormat` and `build_request` (the exact request body), and
the normalized event types. The streaming client comes in a later module.
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
from rookwise.harness.request import ChatRequest, JsonSchemaFormat, RequestError, build_request

__all__ = [
    "ChatRequest",
    "ConfigError",
    "ErrorEvent",
    "Event",
    "Finish",
    "HarnessConfig",
    "JsonSchemaFormat",
    "ReasoningDelta",
    "RequestError",
    "StreamStart",
    "TextDelta",
    "UsageEvent",
    "build_request",
    "load_config",
]
