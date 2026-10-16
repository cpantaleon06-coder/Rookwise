"""Streaming probe for Nebius Token Factory with NVIDIA Nemotron models.

Answers the streaming questions the harness depends on, by observation only:
the final usage chunk and its field names, reasoning and cached token fields, chunk
shapes (`delta.content`, reasoning fields, role chunk, `finish_reason`, `[DONE]`,
empty or null content), what happens when the client closes the connection
mid-stream, and the response headers useful for rate limiting.

For each Nemotron model in config/prices.json it sends three streaming requests with
`stream_options.include_usage`:
- `off`: reasoning off (`chat_template_kwargs.enable_thinking=false`), max_tokens 48
- `cancel`: reasoning off, max_tokens 64, closed by the client after a few content chunks
- `on`: reasoning on (`enable_thinking=true`), max_tokens 256

It talks to the API with raw httpx so it sees the SSE lines exactly as sent. Before
each call it checks the worst-case cost against a hard cap (USD 0.05 by default) and
aborts the run if the cap would be passed. Prices come only from config/prices.json.
Raw results go to runs/stream_probe.json (gitignored). The markdown summary, with each
line tagged VERIFIED (observed in this run) or UNVERIFIED, goes to runs/stream_probe.md
and, with --write-docs, is appended to docs/HARNESS_RESEARCH.md.

If NEBIUS_API_KEY is not set, the live part is skipped and every item is UNVERIFIED.
The key is read from the environment (loaded from .env) and never printed or stored.

Usage:
    python scripts/stream_probe.py               # run, write runs/stream_probe.{json,md}
    python scripts/stream_probe.py --write-docs  # also append the section to the docs
    python scripts/stream_probe.py --from-json   # no calls: rebuild the summary from the JSON
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = REPO_ROOT / "config" / "prices.json"
DOCS_PATH = REPO_ROOT / "docs" / "HARNESS_RESEARCH.md"
OUT_JSON = REPO_ROOT / "runs" / "stream_probe.json"
OUT_MD = REPO_ROOT / "runs" / "stream_probe.md"
DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"

MAX_USD = 0.05
# Extra input tokens assumed for the chat template when reserving before a call.
TEMPLATE_MARGIN_TOKENS = 64
# The cancel probe closes the connection after this many chunks with content.
CANCEL_AFTER_CONTENT_CHUNKS = 3
# Headers recorded with their values. Every other header is recorded by name only.
VALUE_HEADERS = ("retry-after", "content-type", "transfer-encoding", "x-request-id")

COUNT_PROMPT = "Count from 1 to 10, separated by spaces. Reply with the numbers only."
LONG_PROMPT = "Write the numbers from 1 to 100, separated by spaces. Reply with the numbers only."
WORD_PROBLEM = "A shop sells 3 pens for $2. How much do 12 pens cost? Reply with only the amount."

PROBES: list[dict[str, Any]] = [
    {"name": "off", "prompt": COUNT_PROMPT, "max_tokens": 48, "thinking": False},
    {
        "name": "cancel",
        "prompt": LONG_PROMPT,
        "max_tokens": 64,
        "thinking": False,
        "cancel_after": CANCEL_AFTER_CONTENT_CHUNKS,
    },
    {"name": "on", "prompt": WORD_PROBLEM, "max_tokens": 256, "thinking": True},
]


def load_models() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    data = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    ids = {k: v for k, v in data["model_ids"].items() if not k.startswith("_")}
    return data["per_million_tokens"], ids


def worst_case_usd(prompt: str, max_tokens: int, price: dict[str, Any]) -> float:
    """Every prompt character as a token, plus the template margin, plus max_tokens."""
    return (
        (len(prompt) + TEMPLATE_MARGIN_TOKENS) * price["input"] + max_tokens * price["output"]
    ) / 1_000_000


def usage_usd(usage: dict[str, Any], price: dict[str, Any]) -> float:
    """Cost formula from docs/ARCHITECTURE.md; a null cached price falls back to input."""
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    output = completion + reasoning if reasoning > completion else completion
    cached_price = price["input"] if price.get("cached_input") is None else price["cached_input"]
    return (
        (prompt - cached) * price["input"] + cached * cached_price + output * price["output"]
    ) / 1_000_000


def _headers(headers: httpx.Headers) -> dict[str, Any]:
    names = sorted({k.lower() for k in headers.keys()})
    values = {k: headers[k] for k in names if k in VALUE_HEADERS or k.startswith("x-ratelimit")}
    return {"names": names, "values": values}


def run_probe(client: httpx.Client, model_id: str, probe: dict[str, Any]) -> dict[str, Any]:
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": probe["prompt"]}],
        "max_tokens": probe["max_tokens"],
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": probe["thinking"]},
    }
    record: dict[str, Any] = {
        "probe": probe["name"],
        "request": body,
        "status_code": None,
        "headers": {},
        "lines": [],
        "chunks": [],
        "done_seen": False,
        "lines_after_done": [],
        "closed_by_client": False,
        "close_error": None,
        "error": None,
    }
    cancel_after = probe.get("cancel_after")
    content_chunks = 0
    started = time.perf_counter()
    try:
        with client.stream("POST", "chat/completions", json=body) as response:
            record["status_code"] = response.status_code
            record["headers"] = _headers(response.headers)
            if response.status_code != 200:
                record["error"] = response.read().decode("utf-8", "replace")[:2000]
                return record
            for line in response.iter_lines():
                elapsed = round(time.perf_counter() - started, 3)
                if record["done_seen"]:
                    record["lines_after_done"].append(line)
                    continue
                if not line.startswith("data:"):
                    # Comments, event names and the blank lines between events.
                    record["lines"].append({"t": elapsed, "raw": line})
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    record["done_seen"] = True
                    record["lines"].append({"t": elapsed, "raw": line})
                    continue
                chunk = json.loads(payload)
                record["chunks"].append({"t": elapsed, "chunk": chunk})
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        content_chunks += 1
                if cancel_after is not None and content_chunks >= cancel_after:
                    record["closed_by_client"] = True
                    break
            if record["closed_by_client"]:
                try:
                    response.close()
                except Exception as exc:  # record whatever the close does
                    record["close_error"] = f"{type(exc).__name__}: {exc}"
    except httpx.HTTPError as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["latency_s"] = round(time.perf_counter() - started, 3)
    return record


# ---------------------------------------------------------------------------
# Analysis: facts only from what was observed


def _usage_chunks(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [c["chunk"] for c in record["chunks"] if c["chunk"].get("usage")]


def _key_paths(obj: Any, prefix: str = "") -> list[str]:
    if not isinstance(obj, dict):
        return [prefix]
    paths: list[str] = []
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            paths.append(path)
            paths.extend(_key_paths(value, path))
        else:
            paths.append(path)
    return paths


def analyze(record: dict[str, Any]) -> dict[str, Any]:
    chunks = [c["chunk"] for c in record["chunks"]]
    delta_keys: set[str] = set()
    chunk_keys: set[str] = set()
    choice_keys: set[str] = set()
    finish_reasons: list[str] = []
    role_chunks = 0
    content_empty = content_null = content_missing = 0
    usage_null_chunks = 0
    choices_empty_chunks = 0
    for chunk in chunks:
        chunk_keys.update(chunk)
        if "usage" in chunk and chunk["usage"] is None:
            usage_null_chunks += 1
        choices = chunk.get("choices")
        if choices == []:
            choices_empty_chunks += 1
        for choice in choices or []:
            choice_keys.update(choice)
            delta = choice.get("delta") or {}
            delta_keys.update(delta)
            if "role" in delta:
                role_chunks += 1
            if "content" not in delta:
                content_missing += 1
            elif delta["content"] is None:
                content_null += 1
            elif delta["content"] == "":
                content_empty += 1
            if choice.get("finish_reason") is not None:
                finish_reasons.append(choice["finish_reason"])
    usage_chunks = _usage_chunks(record)
    last_usage = usage_chunks[-1]["usage"] if usage_chunks else None
    usage_is_last_chunk = bool(chunks) and bool(chunks[-1].get("usage"))
    final_empty = bool(usage_chunks) and usage_chunks[-1].get("choices") == []
    reasoning_keys = sorted(k for k in delta_keys if "reason" in k)
    reasoning_chars = {
        key: sum(
            len((choice.get("delta") or {}).get(key) or "")
            for chunk in chunks
            for choice in chunk.get("choices") or []
        )
        for key in reasoning_keys
    }
    content_text = "".join(
        (choice.get("delta") or {}).get("content") or ""
        for chunk in chunks
        for choice in chunk.get("choices") or []
    )
    reasoning_texts = {
        key: "".join(
            (choice.get("delta") or {}).get(key) or ""
            for chunk in chunks
            for choice in chunk.get("choices") or []
        )
        for key in reasoning_keys
    }
    content_chunks = sum(
        1
        for chunk in chunks
        for choice in chunk.get("choices") or []
        if (choice.get("delta") or {}).get("content")
    )
    first_delta = next((c["choices"][0].get("delta") for c in chunks if c.get("choices")), None)
    first_content_t = next(
        (
            c["t"]
            for c in record["chunks"]
            for choice in c["chunk"].get("choices") or []
            if (choice.get("delta") or {}).get("content")
        ),
        None,
    )
    non_data_lines = sorted(
        {
            entry["raw"]
            for entry in record["lines"]
            if entry["raw"] != "" and not entry["raw"].startswith("data:")
        }
    )
    return {
        "status_code": record["status_code"],
        "error": record["error"],
        "chunk_count": len(chunks),
        "chunk_keys": sorted(chunk_keys),
        "choice_keys": sorted(choice_keys),
        "delta_keys": sorted(delta_keys),
        "reasoning_keys": reasoning_keys,
        "reasoning_chars": reasoning_chars,
        "content_chars": len(content_text),
        "content_chunks": content_chunks,
        "reasoning_fields_identical": len(set(reasoning_texts.values())) == 1
        and len(reasoning_texts) > 1,
        "content_repeats_reasoning": bool(content_text)
        and content_text.strip() in {t.strip() for t in reasoning_texts.values()},
        "first_delta": first_delta,
        "role_chunks": role_chunks,
        "content_empty_string": content_empty,
        "content_null": content_null,
        "content_missing": content_missing,
        "finish_reasons": finish_reasons,
        "done_seen": record["done_seen"],
        "lines_after_done": record["lines_after_done"],
        "non_data_lines": non_data_lines,
        "usage_chunk_count": len(usage_chunks),
        "usage_is_last_chunk": usage_is_last_chunk,
        "final_usage_chunk_has_empty_choices": final_empty,
        "usage_null_chunks": usage_null_chunks,
        "choices_empty_chunks": choices_empty_chunks,
        "usage": last_usage,
        "usage_paths": sorted(_key_paths(last_usage)) if last_usage else [],
        "closed_by_client": record["closed_by_client"],
        "close_error": record["close_error"],
        "first_content_s": first_content_t,
        "latency_s": record.get("latency_s"),
        "header_names": record["headers"].get("names", []),
        "header_values": record["headers"].get("values", {}),
    }


# ---------------------------------------------------------------------------
# Markdown


def _fmt(value: Any) -> str:
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def _unverified_section(today: str, reason: str) -> str:
    items = [
        "Whether a final chunk carries `usage`, and its exact field names",
        "Whether reasoning tokens are reported in streaming usage",
        "Whether `prompt_tokens_details.cached_tokens` is present in streaming usage",
        "Chunk shapes: `delta.content`, reasoning field names, role chunk, `finish_reason` "
        "values, `[DONE]`, empty or null content chunks",
        "Behavior when the client closes the connection mid-stream",
        "Rate-limit response headers on streaming responses",
    ]
    lines = [f"## Streaming probe ({today})", "", f"Live part skipped: {reason}.", ""]
    lines += [f"- UNVERIFIED: {item}." for item in items]
    return "\n".join(lines) + "\n"


def _usage_delivery(facts: dict[str, Any]) -> str:
    if not facts["usage_chunk_count"]:
        return "no chunk carried non-null `usage`"
    final = facts["final_usage_chunk_has_empty_choices"]
    if facts["usage_chunk_count"] == facts["chunk_count"]:
        return (
            f"`usage` on every chunk ({facts['usage_chunk_count']} of {facts['chunk_count']}) as "
            "running totals; the last JSON chunk has `choices: []` "
            f"({final}) and the final totals"
        )
    return (
        f"`usage` on {facts['usage_chunk_count']} of {facts['chunk_count']} chunks; the last "
        f"JSON chunk carries it: {facts['usage_is_last_chunk']}; it has `choices: []`: {final}"
    )


def _model_lines(alias: str, by_probe: dict[str, dict[str, Any]]) -> list[str]:
    off, cancel, on = by_probe.get("off"), by_probe.get("cancel"), by_probe.get("on")
    lines = [f"### {alias}", ""]
    for name, facts in (("off", off), ("cancel", cancel), ("on", on)):
        if facts is None:
            lines.append(f"- UNVERIFIED: `{name}` probe not run.")
        elif facts["status_code"] != 200:
            lines.append(
                f"- VERIFIED: `{name}` returned HTTP {facts['status_code']} "
                f"({(facts['error'] or '')[:200]})."
            )
    for name, facts in (("off", off), ("on", on)):
        if facts is None or facts["status_code"] != 200:
            continue
        tag = f"VERIFIED ({'reasoning off' if name == 'off' else 'reasoning on'})"
        lines.append(f"- {tag}: {_usage_delivery(facts)}.")
        if facts["usage"]:
            lines.append(f"- {tag}: final usage {_fmt(facts['usage'])}.")
        lines.append(
            f"- {tag}: {facts['chunk_count']} JSON chunks; delta keys "
            f"{_fmt(facts['delta_keys'])}; first delta {_fmt(facts['first_delta'])}; "
            f"`finish_reason` values {_fmt(facts['finish_reasons'])}."
        )
        lines.append(
            f'- {tag}: `delta.content` "" in {facts["content_empty_string"]} chunk(s), null in '
            f"{facts['content_null']}, absent in {facts['content_missing']}; "
            f"{facts['content_chars']} content chars."
        )
        if facts["reasoning_keys"]:
            same = " (identical text in each field)" if facts["reasoning_fields_identical"] else ""
            lines.append(
                f"- {tag}: reasoning text in delta field(s) {_fmt(facts['reasoning_keys'])}, "
                f"chars {_fmt(facts['reasoning_chars'])}{same}."
            )
        if facts["content_repeats_reasoning"]:
            lines.append(
                f"- {tag}: the content is the reasoning text again, sent as "
                f"{facts['content_chunks']} content chunk(s) after the reasoning deltas."
            )
        lines.append(
            f"- {tag}: `[DONE]` seen: {facts['done_seen']}; only blank lines between events "
            f'(non-data lines {_fmt(facts["non_data_lines"])}); `"usage": null` chunks: '
            f"{facts['usage_null_chunks']}."
        )
    if cancel is not None and cancel["status_code"] == 200:
        lines.append(
            f"- VERIFIED (client close): closed after {cancel['chunk_count']} JSON chunks; "
            f"`usage` chunks received before the close: {cancel['usage_chunk_count']} "
            "(final `choices: []` chunk received: "
            f"{cancel['final_usage_chunk_has_empty_choices']}); "
            f"error raised by the close: {_fmt(cancel['close_error'])}."
        )
    first = off or on or cancel
    if first and first["status_code"] == 200:
        values = first["header_values"]
        limits = {k: v for k, v in values.items() if k.startswith("x-ratelimit")}
        lines.append(
            f"- VERIFIED (headers, `off` call): `retry-after` present: "
            f"{'retry-after' in first['header_names']}; x-ratelimit headers {_fmt(limits)}."
        )
    lines.append("")
    return lines


def build_markdown(
    today: str, results: dict[str, dict[str, dict[str, Any]]], spend: float, notes: list[str]
) -> str:
    lines = [
        f"## Streaming probe ({today})",
        "",
        "Observed with `scripts/stream_probe.py` (raw results in `runs/stream_probe.json`, "
        "gitignored). Per model, three streaming requests with "
        "`stream_options.include_usage: true`: `off` (reasoning off, max_tokens 48), `cancel` "
        f"(reasoning off, max_tokens 64, closed by the client after {CANCEL_AFTER_CONTENT_CHUNKS} "
        "content chunks) and `on` (reasoning on via `chat_template_kwargs.enable_thinking: true`, "
        f"max_tokens 256). One sample each. Estimated spend: USD {spend:.6f}.",
        "",
        "- UNVERIFIED (client close): what the server does after the client closes the "
        "connection, and whether or how much it bills, is not observable from the client.",
        "- UNVERIFIED: whether `retry-after` is sent on HTTP 429 for streaming requests "
        "(no 429 happened).",
        "",
    ]
    for note in notes:
        lines.append(f"- {note}")
    if notes:
        lines.append("")
    for alias, by_probe in results.items():
        lines += _model_lines(alias, by_probe)
    return "\n".join(lines)


# ---------------------------------------------------------------------------


def call_spend(record: dict[str, Any], price: dict[str, Any], reserve: float) -> float:
    """Estimated cost of one probe call.

    Only the final usage (the `choices: []` chunk) counts as real usage. Running totals
    from a stream closed early are a lower bound, so such a call counts as the worst case.
    """
    usage_chunks = _usage_chunks(record)
    if usage_chunks and usage_chunks[-1].get("choices") == []:
        return usage_usd(usage_chunks[-1]["usage"], price)
    if record["status_code"] is not None and 400 <= record["status_code"] < 500:
        return 0.0  # rejected before generation
    return reserve


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--write-docs", action="store_true")
    parser.add_argument("--max-usd", type=float, default=MAX_USD)
    parser.add_argument(
        "--from-json",
        action="store_true",
        help="no API calls: rebuild the summary from runs/stream_probe.json",
    )
    args = parser.parse_args()
    max_usd = min(args.max_usd, MAX_USD)

    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("NEBIUS_API_KEY", "").strip()
    base_url = os.getenv("NEBIUS_BASE_URL", "").strip() or DEFAULT_BASE_URL
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    prices, model_ids = load_models()

    if args.from_json:
        raw = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        today = raw["started"][:10]
        results, spend = {}, 0.0
        for alias in model_ids:
            results[alias] = {}
            for probe in PROBES:
                record = raw.get(alias, {}).get(probe["name"])
                if record is None:
                    continue
                reserve = worst_case_usd(probe["prompt"], probe["max_tokens"], prices[alias])
                spend += call_spend(record, prices[alias], reserve)
                results[alias][probe["name"]] = analyze(record)
        markdown = build_markdown(today, results, spend, raw.get("notes", []))
        OUT_MD.write_text(markdown, encoding="utf-8")
        print(f"Rebuilt {OUT_MD.name} from {OUT_JSON.name}. Estimated spend: USD {spend:.6f}.")
        if args.write_docs:
            _append_docs(markdown)
        return 0

    if not api_key:
        markdown = _unverified_section(today, "NEBIUS_API_KEY is not set")
        OUT_MD.parent.mkdir(exist_ok=True)
        OUT_MD.write_text(markdown, encoding="utf-8")
        print("NEBIUS_API_KEY is not set: live part skipped, every item UNVERIFIED.")
        if args.write_docs:
            _append_docs(markdown)
        return 0

    spend = 0.0
    notes: list[str] = []
    raw = {"started": datetime.now(UTC).isoformat(), "max_usd": max_usd}
    results = {}
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = httpx.Timeout(60.0, connect=10.0)
    with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
        for alias, model_id in model_ids.items():
            price = prices[alias]
            results[alias] = {}
            raw[alias] = {}
            for probe in PROBES:
                reserve = worst_case_usd(probe["prompt"], probe["max_tokens"], price)
                if spend + reserve > max_usd:
                    notes.append(
                        f"Aborted before {alias} `{probe['name']}`: estimated spend "
                        f"USD {spend:.6f} plus worst case USD {reserve:.6f} would pass the cap "
                        f"USD {max_usd}."
                    )
                    print(notes[-1])
                    break
                record = run_probe(client, model_id, probe)
                spend += call_spend(record, price, reserve)
                raw[alias][probe["name"]] = record
                results[alias][probe["name"]] = analyze(record)
                facts = results[alias][probe["name"]]
                print(
                    f"{alias:<24} {probe['name']:<7} status={facts['status_code']} "
                    f"chunks={facts['chunk_count']} usage_chunks={facts['usage_chunk_count']} "
                    f"finish={facts['finish_reasons']} spend=USD {spend:.6f}"
                )
            else:
                continue
            break

    raw["notes"] = notes
    raw["estimated_spend_usd"] = round(spend, 6)
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown = build_markdown(today, results, spend, notes)
    OUT_MD.write_text(markdown, encoding="utf-8")
    print(f"Estimated spend: USD {spend:.6f}. Wrote {OUT_JSON.name} and {OUT_MD.name}.")
    if args.write_docs:
        _append_docs(markdown)
    return 0


def _append_docs(markdown: str) -> None:
    text = DOCS_PATH.read_text(encoding="utf-8").rstrip("\n")
    DOCS_PATH.write_text(text + "\n\n" + markdown.rstrip("\n") + "\n", encoding="utf-8")
    print(f"Appended the section to {DOCS_PATH.relative_to(REPO_ROOT)}.")


if __name__ == "__main__":
    sys.exit(main())
