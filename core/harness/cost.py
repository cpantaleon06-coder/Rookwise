"""Usage parsing and cost, using the "Cost of a call" formula in docs/ARCHITECTURE.md.

The formula itself lives in `rookwise.ledger.call_cost`, so the ledger and the harness
can never disagree on a price. This module turns the API's `usage` object into a
`ledger.Usage`, and builds the usage to charge when the API sent none
(`on_missing_usage` in config/harness.json).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from rookwise.ledger import CallCost, ModelPrice, Usage, call_cost

__all__ = [
    "CallCost",
    "call_cost",
    "cost_usd",
    "estimate_usage_from_text",
    "full_reservation_usage",
    "parse_usage",
]


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def parse_usage(raw: Mapping[str, Any]) -> Usage:
    """Read `usage` from a chunk.

    - `input_tokens` is `prompt_tokens`, `output_tokens` is `completion_tokens`.
    - `cached_tokens` is `prompt_tokens_details.cached_tokens`; a missing or null value
      (Lightning sends `prompt_tokens_details: null`, Nano sends none) counts as 0. The
      undocumented `prompt_cache_hit_tokens` field is not used: it was 0 in every call so
      far and its billing meaning is UNVERIFIED.
    - `reasoning_tokens` is `completion_tokens_details.reasoning_tokens`, 0 when absent.
      `completion_tokens` already includes them (VERIFIED on all four models,
      HARNESS_RESEARCH.md, "Reasoning token accounting"), so they are billed once, as
      part of the output. `call_cost` adds them only if a response ever reports more
      reasoning than completion tokens, which no observed call did. Whether Token
      Factory bills them at the output price is still UNVERIFIED (no console check).
    """
    prompt_details = raw.get("prompt_tokens_details") or {}
    completion_details = raw.get("completion_tokens_details") or {}
    input_tokens = _int(raw.get("prompt_tokens"))
    cached = min(_int(prompt_details.get("cached_tokens")), input_tokens)
    return Usage(
        input_tokens=input_tokens,
        output_tokens=_int(raw.get("completion_tokens")),
        cached_tokens=cached,
        reasoning_tokens=_int(completion_details.get("reasoning_tokens")),
    )


def cost_usd(price: ModelPrice, usage: Usage) -> float:
    return call_cost(price, usage).usd


def full_reservation_usage(input_tokens_estimate: int, max_tokens: int) -> Usage:
    """`charge_full_reservation`: the usage the reservation was sized for, so the charge
    equals the reservation exactly. The safe default when the API sent no usage."""
    return Usage(input_tokens=input_tokens_estimate, output_tokens=max_tokens)


def estimate_usage_from_text(
    input_tokens_estimate: int,
    text: str,
    reasoning: str,
    chars_per_token: float,
    max_tokens: int,
    running: Usage | None = None,
) -> Usage:
    """`estimate_from_text`: LESS SAFE. Output tokens are guessed from the characters
    received, which can undercount (for example tokens generated after the client
    stopped reading). A running total from the stream (Ultra and Nano send one on every
    chunk) is a lower bound, so the larger of the two is used, capped at `max_tokens`."""
    output = math.ceil((len(text) + len(reasoning)) / chars_per_token)
    input_tokens = input_tokens_estimate
    if running is not None:
        output = max(output, running.output_tokens, running.reasoning_tokens)
        input_tokens = running.input_tokens or input_tokens
    return Usage(input_tokens=input_tokens, output_tokens=min(output, max_tokens))
