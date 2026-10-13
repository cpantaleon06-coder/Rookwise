"""Smoke test for Nebius Token Factory with NVIDIA Nemotron models.

Covers items 2 to 7 of the "First-call checklist" in docs/HARNESS_RESEARCH.md:
rate-limit headers, plain chat (sent twice with the identical prompt to see whether
`cached_tokens` shows up), reasoning on versus off (`reasoning_effort` and
`extra_body.chat_template_kwargs.enable_thinking`), tool calling, json_schema output
(wrapped and bare schema) and a short non-English prompt. Every call records latency and
end-to-end output tokens per second, to check the speeds listed in the console.

Every call uses max_tokens <= 600. Each error is caught and recorded, then the script
moves on. Before each call it reserves a worst-case cost and stops the whole run if the
estimated spend would pass the cap (USD 0.25 by default). Prices come only from
config/prices.json, with the cost formula from docs/ARCHITECTURE.md. Raw results are
written to runs/smoke_test.json (gitignored).

Usage:
    python scripts/smoke_test.py                  # list models, test every Nemotron model
    python scripts/smoke_test.py --list-only      # only GET /models, no chat calls
    python scripts/smoke_test.py --models ID1,ID2 # test only these model IDs
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = REPO_ROOT / "config" / "prices.json"
DEFAULT_OUT = REPO_ROOT / "runs" / "smoke_test.json"

MAX_TOKENS = 600
DEFAULT_MAX_USD = 0.25
# Extra input tokens assumed for the chat template and any server-side system prompt
# when reserving budget before a call. The real count comes from `usage` afterwards.
TEMPLATE_MARGIN_TOKENS = 256
MAX_RETRY_AFTER_WAIT_S = 60.0
# Short answers make tokens per second mostly network and prompt time, so the speed
# summary only uses calls with at least this many output tokens.
MIN_OUTPUT_TOKENS_FOR_SPEED = 100

# A long, fixed system message for the two plain chat calls. Prefix caches work on
# long shared prefixes, so a tiny prompt could hide caching even where it exists.
CACHE_CONTEXT = "You are a concise assistant for a small business. House rules:\n" + "\n".join(
    f"Rule {i}: answer in plain English, stay polite, and keep replies under 20 words."
    for i in range(1, 101)
)
PLAIN_MESSAGES = [
    {"role": "system", "content": CACHE_CONTEXT},
    {"role": "user", "content": "Reply with a short greeting of at most five words."},
]

WORD_PROBLEM = "A shop sells 3 pens for $2. How much do 12 pens cost? Reply with only the amount."

ADD_TOOL = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two numbers and return the sum.",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
}

CITY_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": "string"},
        "country": {"type": "string"},
        "is_capital": {"type": "boolean"},
    },
    "required": ["city", "country", "is_capital"],
    "additionalProperties": False,
}

# The docs advise putting the schema in the prompt as well as in response_format.
JSON_PROMPT = (
    "Describe the city of Paris as a JSON object that matches this JSON Schema. "
    f"Return only the JSON object.\n{json.dumps(CITY_SCHEMA)}"
)


class CityFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str
    country: str
    is_capital: bool


def _user(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def _thinking(enabled: bool) -> dict[str, Any]:
    return {"chat_template_kwargs": {"enable_thinking": enabled}}


# kind decides how the response is checked: chat, reasoning, tool or json.
TESTS: list[dict[str, Any]] = [
    {"name": "plain_chat", "kind": "chat", "params": {"messages": PLAIN_MESSAGES}},
    # Identical request, sent right after the first one, to see whether caching shows up.
    {"name": "plain_chat_2", "kind": "chat", "params": {"messages": PLAIN_MESSAGES}},
    {"name": "reason_default", "kind": "reasoning", "params": {"messages": _user(WORD_PROBLEM)}},
    {
        "name": "effort_low",
        "kind": "reasoning",
        "params": {"messages": _user(WORD_PROBLEM), "reasoning_effort": "low"},
    },
    {
        "name": "effort_high",
        "kind": "reasoning",
        "params": {"messages": _user(WORD_PROBLEM), "reasoning_effort": "high"},
    },
    {
        "name": "effort_none",
        "kind": "reasoning",
        "params": {"messages": _user(WORD_PROBLEM), "reasoning_effort": "none"},
    },
    {
        "name": "thinking_off",
        "kind": "reasoning",
        "params": {"messages": _user(WORD_PROBLEM), "extra_body": _thinking(False)},
    },
    {
        "name": "thinking_on",
        "kind": "reasoning",
        "params": {"messages": _user(WORD_PROBLEM), "extra_body": _thinking(True)},
    },
    {
        "name": "tool_call",
        "kind": "tool",
        "params": {
            "messages": _user(
                "Use the add tool to compute 17 + 25 and, separately, 40 + 2. "
                "Call the tool once for each sum."
            ),
            "tools": [ADD_TOOL],
        },
    },
    {
        "name": "json_wrapped",
        "kind": "json",
        "params": {
            "messages": _user(JSON_PROMPT),
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "city_fact", "schema": CITY_SCHEMA, "strict": True},
            },
        },
    },
    {
        "name": "json_bare",
        "kind": "json",
        "params": {
            "messages": _user(JSON_PROMPT),
            "response_format": {"type": "json_schema", "json_schema": CITY_SCHEMA},
        },
    },
    {
        "name": "non_english",
        "kind": "chat",
        "params": {
            "messages": _user(
                "Responde en español, en una sola frase: ¿por qué una pequeña tienda de "
                "barrio debería tener presencia en internet?"
            )
        },
    },
]


# ---------------------------------------------------------------------------
# Prices and spend


def load_prices(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    per_million = data["per_million_tokens"]
    model_ids = {
        alias: model_id
        for alias, model_id in data.get("model_ids", {}).items()
        if not alias.startswith("_") and model_id
    }
    return per_million, model_ids


def resolve_price(
    model_id: str, per_million: dict[str, dict[str, Any]], model_ids: dict[str, str]
) -> dict[str, Any]:
    """Map an API model ID to a price entry in config/prices.json.

    1. Exact match against `model_ids` (once they are filled in).
    2. Otherwise a single unambiguous name match on the alias suffix (ultra, super, ...).
    3. Otherwise the highest input and output prices in the file, so the cap stays safe.
    """
    for alias, mapped_id in model_ids.items():
        if mapped_id == model_id and alias in per_million:
            return {"alias": alias, **per_million[alias], "how": "model_ids"}
    lowered = model_id.lower()
    hits = [alias for alias in per_million if alias.rsplit("-", 1)[-1] in lowered]
    if len(hits) == 1:
        return {"alias": hits[0], **per_million[hits[0]], "how": "name match (unconfirmed)"}
    return {
        "alias": None,
        "input": max(p["input"] for p in per_million.values()),
        "cached_input": None,
        "output": max(p["output"] for p in per_million.values()),
        "how": "highest price in file (no match)",
    }


def cost_usd(
    input_tokens: int, output_tokens: int, price: dict[str, Any], cached_tokens: int = 0
) -> float:
    """Cost formula from docs/ARCHITECTURE.md. A null cached_input price falls back to input."""
    cached_price = price["input"] if price.get("cached_input") is None else price["cached_input"]
    return (
        (input_tokens - cached_tokens) * price["input"]
        + cached_tokens * cached_price
        + output_tokens * price["output"]
    ) / 1_000_000


def output_tokens(completion: int | None, reasoning: int | None) -> int | None:
    """Output tokens to bill. Reasoning tokens count as output until verified.

    UNVERIFIED whether `completion_tokens` already includes reasoning tokens. If a response
    reports more reasoning than completion tokens, they are clearly not included: add them.
    """
    if completion is None:
        return None
    reasoning = reasoning or 0
    return completion + reasoning if reasoning > completion else completion


def reserve_usd(params: dict[str, Any], price: dict[str, Any]) -> float:
    """Worst-case cost of a call, estimated before sending it (about 2 chars per token)."""
    payload = {k: params.get(k) for k in ("messages", "tools", "response_format")}
    est_input = len(json.dumps(payload)) // 2 + TEMPLATE_MARGIN_TOKENS
    return cost_usd(est_input, params["max_tokens"], price)


def billed_usd(record: dict[str, Any], price: dict[str, Any], reserved: float) -> float:
    """Estimated cost of a finished call, from the usage the API returned."""
    prompt = record.get("prompt_tokens")
    output = record.get("output_tokens")
    if prompt is not None and output is not None:
        return cost_usd(prompt, output, price, record.get("cached_tokens") or 0)
    status = record.get("status_code")
    if status is not None and 400 <= status < 500:
        return 0.0  # rejected before generation
    return reserved  # unknown outcome (timeout, 5xx, unparsable body): assume the worst


# ---------------------------------------------------------------------------
# One call


# A <think> block inside `content`, closed or cut off by max_tokens.
THINK_BLOCK = re.compile(r"<think>(.*?)(?:</think>|$)", flags=re.DOTALL)


def _answer_text(content: str | None) -> str:
    """The content without any <think> block, i.e. the part a caller would use."""
    return THINK_BLOCK.sub("", content or "").strip()


def _ratelimit_headers(headers: Any) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items() if k.lower().startswith("x-ratelimit")}


def _reasoning_text_chars(message: dict[str, Any]) -> int:
    """Characters of visible reasoning text, wherever the server puts it."""
    total = 0
    for field in ("reasoning_content", "reasoning"):
        value = message.get(field)
        if isinstance(value, str):
            total += len(value)
    for block in THINK_BLOCK.findall(message.get("content") or ""):
        total += len(block)
    return total


def _check(kind: str, record: dict[str, Any]) -> dict[str, Any]:
    content = _answer_text(record.get("content"))
    if kind == "reasoning":
        # Expected answer: $8. Numbers inside a <think> block do not count.
        return {"answer_correct": bool(re.search(r"(?<![\d.])8(?:\.0+)?(?!\.?\d)", content))}
    if kind == "tool":
        return {"tool_call_count": len(record.get("tool_calls") or [])}
    if kind == "json":
        if not content:
            return {"json_parsed": False, "schema_valid": False}
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            return {"json_parsed": False, "schema_valid": False}
        try:
            CityFact.model_validate(obj)
        except ValidationError:
            return {"json_parsed": True, "schema_valid": False}
        return {"json_parsed": True, "schema_valid": True}
    return {}


def run_call(client: OpenAI, model_id: str, test: dict[str, Any]) -> dict[str, Any]:
    params = {"model": model_id, "max_tokens": MAX_TOKENS, **test["params"]}
    record: dict[str, Any] = {
        "model": model_id,
        "test": test["name"],
        "kind": test["kind"],
        "request": params,
        "ok": False,
        "status_code": None,
        "error": None,
        "ratelimit_headers": {},
    }
    headers: Any = {}
    started = time.perf_counter()
    try:
        raw = client.chat.completions.with_raw_response.create(**params)
        headers = raw.headers
        record["status_code"] = raw.status_code
        data = raw.parse().model_dump()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        record.update(
            ok=True,
            prompt_tokens=usage.get("prompt_tokens"),
            cached_tokens=prompt_details.get("cached_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            reasoning_tokens=completion_details.get("reasoning_tokens"),
            finish_reason=choice.get("finish_reason"),
            content=message.get("content"),
            refusal=message.get("refusal"),
            tool_calls=message.get("tool_calls") or [],
            reasoning_text_chars=_reasoning_text_chars(message),
            response=data,
        )
        record["output_tokens"] = output_tokens(
            record["completion_tokens"], record["reasoning_tokens"]
        )
    except APIStatusError as exc:
        headers = exc.response.headers
        record.update(status_code=exc.status_code, error=str(exc), error_body=exc.body)
    except APIConnectionError as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # keep going whatever happens; the error is recorded
        record["error"] = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    record["latency_s"] = round(elapsed, 2)
    # End to end: includes network and prompt processing, not only decoding.
    record["output_tokens_per_s"] = (
        round(record["output_tokens"] / elapsed, 1)
        if record.get("output_tokens") and elapsed > 0
        else None
    )
    if headers:
        record["ratelimit_headers"] = _ratelimit_headers(headers)
        record["retry_after"] = headers.get("retry-after")
        record["request_id"] = headers.get("x-request-id")
    record["checks"] = _check(test["kind"], record) if record["ok"] else {}
    return record


# ---------------------------------------------------------------------------
# Output


def _short(text: Any, width: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def _cell(value: Any, width: int, align: str = ">") -> str:
    return f"{'-' if value is None else value:{align}{width}}"


HEADER = (
    f"  {'test':<15} {'ok':<3} {'lat_s':>6} {'tok/s':>6} {'prompt':>6} {'cached':>6} "
    f"{'compl':>6} {'rsn_tok':>7} {'rsn_txt':>7} {'tools':>5} {'finish':<10} {'usd':>9}  note"
)


def _note(record: dict[str, Any]) -> str:
    if record["error"]:
        prefix = f"ERR {record['status_code']}: " if record["status_code"] else "ERR "
        return prefix + _short(record["error"], 70)
    checks = record["checks"]
    if record["kind"] == "reasoning":
        verdict = "correct" if checks.get("answer_correct") else "WRONG/EMPTY"
        return f"{verdict}: {_short(_answer_text(record.get('content')), 40)}"
    if record["kind"] == "tool":
        calls = record.get("tool_calls") or []
        if not calls:
            return f"no tool_calls: {_short(_answer_text(record.get('content')), 50)}"
        functions = [call.get("function") or {} for call in calls]
        return _short(" ".join(f"{f.get('name')}{f.get('arguments')}" for f in functions), 70)
    if record["kind"] == "json":
        note = f"parsed={checks.get('json_parsed')} valid={checks.get('schema_valid')}"
        if record.get("refusal"):
            note += f" refusal={_short(record['refusal'], 30)}"
        return note
    return _short(_answer_text(record.get("content")), 70)


def print_row(record: dict[str, Any]) -> None:
    print(
        f"  {record['test']:<15} {'yes' if record['ok'] else 'NO':<3} "
        f"{_cell(record.get('latency_s'), 6)} {_cell(record.get('output_tokens_per_s'), 6)} "
        f"{_cell(record.get('prompt_tokens'), 6)} {_cell(record.get('cached_tokens'), 6)} "
        f"{_cell(record.get('completion_tokens'), 6)} {_cell(record.get('reasoning_tokens'), 7)} "
        f"{_cell(record.get('reasoning_text_chars'), 7)} "
        f"{_cell(len(record.get('tool_calls') or []) if record['ok'] else None, 5)} "
        f"{_cell(record.get('finish_reason'), 10, '<')} {record['usd_estimate']:>9.6f}  "
        f"{_note(record)}"
    )


def print_summary(calls: list[dict[str, Any]]) -> None:
    """Per model: speed (to check the listed speeds) and cached tokens on the repeated call."""
    by_model: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        by_model.setdefault(call["model"], []).append(call)
    if not by_model:
        return
    width = max(len(m) for m in by_model)
    print(
        "\n== Summary per model ==\n"
        "  tok/s is end to end (output tokens / total latency, including network and prompt\n"
        "  processing), so it reads lower than a pure decoding speed. Median over calls with\n"
        f"  at least {MIN_OUTPUT_TOKENS_FOR_SPEED} output tokens (n). cached = cached_tokens on "
        "plain_chat / plain_chat_2."
    )
    print(
        f"  {'model':<{width}} {'calls':>5} {'errors':>6} {'med_lat_s':>9} {'med_tok/s':>9} "
        f"{'n':>3} {'cached':>11} {'usd':>9}"
    )
    for model, model_calls in by_model.items():
        ok = [c for c in model_calls if c["ok"]]
        speeds = [
            c["output_tokens_per_s"]
            for c in ok
            if c.get("output_tokens_per_s")
            and (c.get("output_tokens") or 0) >= MIN_OUTPUT_TOKENS_FOR_SPEED
        ]
        cached = {c["test"]: c.get("cached_tokens") for c in model_calls}
        cached_cell = "/".join(
            "-" if cached.get(t) is None else str(cached[t]) for t in ("plain_chat", "plain_chat_2")
        )
        print(
            f"  {model:<{width}} {len(model_calls):>5} "
            f"{sum(1 for c in model_calls if c['error']):>6} "
            f"{_cell(round(median(c['latency_s'] for c in ok), 2) if ok else None, 9)} "
            f"{_cell(round(median(speeds), 1) if speeds else None, 9)} {len(speeds):>3} "
            f"{cached_cell:>11} {sum(c['usd_estimate'] for c in model_calls):>9.6f}"
        )


def write_results(path: Path, results: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), "utf-8")
    print(f"\nRaw results written to {path}")


# ---------------------------------------------------------------------------
# Main


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list-only", action="store_true", help="only list models, no chat calls")
    parser.add_argument(
        "--models", help="comma-separated model IDs to test (default: all Nemotron)"
    )
    parser.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD, help="spend cap in USD")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between calls")
    parser.add_argument("--timeout", type=float, default=90.0, help="per-call timeout in seconds")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="raw results JSON path")
    return parser.parse_args(argv)


def run(client: OpenAI, args: argparse.Namespace, results: dict[str, Any]) -> None:
    per_million, model_ids = load_prices(PRICES_PATH)

    print("== GET /models ==")
    try:
        page = client.models.list()
        listed = [m.model_dump() for m in page.data]
    except Exception as exc:  # recorded; the run can still continue with --models
        listed = []
        results["models_error"] = f"{type(exc).__name__}: {exc}"
        print(f"  ERROR listing models: {_short(results['models_error'], 200)}")
    results["models_raw"] = listed
    nemotron = sorted(m["id"] for m in listed if "nemotron" in str(m.get("id", "")).lower())
    results["nemotron_models"] = nemotron
    print(f"  {len(listed)} models listed, {len(nemotron)} contain 'nemotron':")
    for model_id in nemotron:
        print(f"    {model_id}")

    if args.list_only:
        return
    targets = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else nemotron
    if not targets:
        print("\nNo models to test.")
        return

    spent = 0.0
    first_call = True
    for model_id in targets:
        price = resolve_price(model_id, per_million, model_ids)
        price["cached_price_fallback"] = price.get("cached_input") is None
        results["prices_used"][model_id] = price
        cached_note = (
            "not published, input price used"
            if price["cached_price_fallback"]
            else f"USD {price['cached_input']}"
        )
        print(
            f"\n== {model_id} ==\n  price: {price['alias'] or '?'} via {price['how']}, "
            f"USD {price['input']}/{price['output']} per 1M in/out; cached input: {cached_note}"
        )
        for test in TESTS:
            params = {"max_tokens": MAX_TOKENS, **test["params"]}
            reserved = reserve_usd(params, price)
            if spent + reserved > args.max_usd:
                results["stopped_reason"] = (
                    f"spend cap: estimated {spent:.4f} + worst case {reserved:.4f} "
                    f"for {model_id}/{test['name']} would pass USD {args.max_usd}"
                )
                print(f"\nSTOPPED. {results['stopped_reason']}")
                return
            if not first_call:
                time.sleep(args.pause)
            first_call = False

            record = run_call(client, model_id, test)
            record["usd_estimate"] = billed_usd(record, price, reserved)
            spent += record["usd_estimate"]
            results["estimated_spend_usd"] = round(spent, 6)
            results["calls"].append(record)

            limits = record["ratelimit_headers"]
            if limits and model_id not in results["ratelimit_headers"]:
                results["ratelimit_headers"][model_id] = limits
            if test is TESTS[0]:  # print the headers once per model, from its first response
                print("  rate-limit headers:" if limits else "  rate-limit headers: none returned")
                for key, value in limits.items():
                    print(f"    {key}: {value}")
                print(HEADER)
            print_row(record)

            if record["status_code"] == 429:
                try:
                    wait = float(record.get("retry_after") or 5)
                except ValueError:
                    wait = 5.0
                wait = min(wait, MAX_RETRY_AFTER_WAIT_S)
                print(f"  HTTP 429: waiting {wait:.0f}s (Retry-After: {record.get('retry_after')})")
                time.sleep(wait)
            if spent > args.max_usd:
                results["stopped_reason"] = f"spend cap: estimated {spent:.4f} > {args.max_usd}"
                print(f"\nSTOPPED. {results['stopped_reason']}")
                return


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("NEBIUS_API_KEY", "").strip()
    base_url = os.getenv("NEBIUS_BASE_URL", "").strip()
    if not api_key or not base_url:
        print("NEBIUS_API_KEY and NEBIUS_BASE_URL must be set. Copy .env.example to .env.")
        return 1
    print(f"Base URL: {base_url}  (API key loaded, not shown)  cap: USD {args.max_usd}\n")

    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=args.timeout)
    results: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "max_usd": args.max_usd,
        "max_tokens_per_call": MAX_TOKENS,
        "estimated_spend_usd": 0.0,
        "stopped_reason": None,
        "prices_used": {},
        "ratelimit_headers": {},
        "calls": [],
    }
    try:
        run(client, args, results)
    finally:
        results["finished_at"] = datetime.now(UTC).isoformat()
        calls = results["calls"]
        print_summary(calls)
        errors = sum(1 for c in calls if c["error"])
        print(
            f"\n{len(calls)} calls, {errors} errors, "
            f"estimated spend USD {results['estimated_spend_usd']:.6f}"
        )
        write_results(args.out, results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
