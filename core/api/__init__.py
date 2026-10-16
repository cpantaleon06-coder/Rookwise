"""API contract v1 between core/ and web/ (docs/api.md). Models only, no server."""

from rookwise.api.models import (
    API_VERSION,
    EVENT_TYPES,
    SCHEMA_MODELS,
    SSE_EVENT_ADAPTER,
    TERMINAL_EVENTS,
)

__all__ = ["API_VERSION", "EVENT_TYPES", "SCHEMA_MODELS", "SSE_EVENT_ADAPTER", "TERMINAL_EVENTS"]
