"""The model harness: the only code in Rookwise that calls the model API.

Public surface:

- `Harness(ledger, config=None, api_key=None, transport=None, limiter=None, clock=None,
  rng=None, cassette=None)`: one per ledger. `stream(request, cancel=None)` yields
  normalized events; `complete(request, cancel=None)` consumes the stream and returns
  a `Result`. Use it as an async context manager, or call `aclose()`.
- `ChatRequest`, `JsonSchemaFormat`: what to send. Model defaults and quirks come from
  config/harness.json; `build_request` shows the exact body.
- Events: `StreamStart`, `TextDelta`, `ReasoningDelta`, `ToolCallDelta`, `UsageEvent`,
  `Finish`, `ErrorEvent` (the `Event` union); `ToolCall` and `assemble_tool_calls` for
  native tool calls.
- `CancelHandle`: cancel a call from outside; asyncio cancellation works too.
- Errors: `HarnessError` (base), `ApiError` (with a `kind` from the taxonomy),
  `StreamInterrupted`, `RequestError`, `ConfigError`. Budget refusals raise the
  ledger's `CapReached` and nothing is sent.
- Record and replay: `HARNESS_MODE` = live (default), record or replay. `Cassette`
  holds one recording file; replay never calls the API and raises `CassetteMiss`
  when a request was not recorded.
- Tool loop: `ToolLoop(harness, tools).run(request, budget=None, cancel=None)` returns a
  `LoopOutcome`; `Tool`, `ToolContext` and `TokenBudget` describe tools and ceilings.
  The protocol per model (`native_tools` or `json_protocol`) is in config/harness.json.
- Final answers: `validate_final` checks the payload against an operator's output model;
  `run_with_escalation(loop, request, output_model, config=...)` adds repairs and the
  escalation ladder and returns an `EscalationResult` with one `AttemptRecord` per
  attempt and a label (`first_pass_ok`, `ok_after_retry`, `ok_after_escalation`,
  `failed`).
- `load_config`, `HarnessConfig`, `RateLimiter`, `RetryPolicy`, `Clock`.

Every call reserves its worst case in the ledger before it is sent and is settled
exactly once (see client.py). The API key is read from the environment
(`NEBIUS_API_KEY`) or passed in; it is never logged or stored.
"""

from rookwise.harness.cassette import Cassette, CassetteMiss
from rookwise.harness.client import CancelHandle, Harness, Result
from rookwise.harness.config import ConfigError, HarnessConfig, load_config
from rookwise.harness.escalate import AttemptRecord, EscalationResult, run_with_escalation
from rookwise.harness.events import (
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
from rookwise.harness.loop import LoopOutcome, TokenBudget, Tool, ToolContext, ToolLoop
from rookwise.harness.ratelimit import Clock, RateLimiter
from rookwise.harness.request import (
    ChatRequest,
    JsonObjectFormat,
    JsonSchemaFormat,
    RequestError,
    build_request,
)
from rookwise.harness.retry import ApiError, HarnessError, RetryPolicy, StreamInterrupted
from rookwise.harness.validate import Validation, validate_final

__all__ = [
    "ApiError",
    "AttemptRecord",
    "CancelHandle",
    "Cassette",
    "CassetteMiss",
    "ChatRequest",
    "Clock",
    "ConfigError",
    "ErrorEvent",
    "EscalationResult",
    "Event",
    "Finish",
    "Harness",
    "HarnessConfig",
    "HarnessError",
    "JsonObjectFormat",
    "JsonSchemaFormat",
    "LoopOutcome",
    "RateLimiter",
    "ReasoningDelta",
    "RequestError",
    "Result",
    "RetryPolicy",
    "StreamInterrupted",
    "StreamStart",
    "TextDelta",
    "TokenBudget",
    "Tool",
    "ToolCall",
    "ToolCallDelta",
    "ToolContext",
    "ToolLoop",
    "UsageEvent",
    "Validation",
    "assemble_tool_calls",
    "build_request",
    "load_config",
    "run_with_escalation",
    "validate_final",
]
