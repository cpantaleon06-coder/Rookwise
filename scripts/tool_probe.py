"""Tool-calling probe for Nebius Token Factory with NVIDIA Nemotron models, streamed.

Answers, by observation only, what the harness tool loop depends on: are OpenAI-style
`tools` and `tool_choice` accepted, does the model emit a tool call, what the streamed
`delta.tool_calls` fragments look like (index, id, name, arguments pieces), the
`finish_reason`, what happens with reasoning on, what happens when `response_format`
json_schema is sent together with `tools`, whether a follow-up turn with the tool result
gives a final answer, and whether `response_format: json_object` works for the JSON
action protocol (no tools).

Per Nemotron model in config/prices.json, up to six streaming requests:
- `auto`: tools, `tool_choice: "auto"`, reasoning off, max_tokens 128
- `forced`: tools, `tool_choice` naming the function, reasoning off, max_tokens 128
- `reasoning_on`: tools, `tool_choice: "auto"`, reasoning on, max_tokens 512
- `with_schema`: tools plus wrapped json_schema `response_format`, reasoning off, max_tokens 128
- `follow_up`: only if `auto` returned a tool call: the call and a `tool` message with
  the result, reasoning off, max_tokens 64
- `json_action`: no tools, a JSON action protocol prompt, `response_format: json_object`,
  reasoning off, max_tokens 128

Hard cap: the run aborts before any call whose worst case would take the estimated
spend past USD 0.05. Prices come only from config/prices.json. Raw results go to
runs/tool_probe.json (gitignored); the summary, each line tagged VERIFIED (observed in
this run) or UNVERIFIED, to runs/tool_probe.md and, with --write-docs, is appended to
docs/HARNESS_RESEARCH.md. Without NEBIUS_API_KEY the live part is skipped and every
item is UNVERIFIED. The key is read from the environment (loaded from .env) and never
printed or stored.

Usage:
    python scripts/tool_probe.py               # run, write runs/tool_probe.{json,md}
    python scripts/tool_probe.py --write-docs  # also append the section to the docs
    python scripts/tool_probe.py --from-json   # no calls: rebuild the summary from the JSON
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
OUT_JSON = REPO_ROOT / "runs" / "tool_probe.json"
OUT_MD = REPO_ROOT / "runs" / "tool_probe.md"
DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"

MAX_USD = 0.05
TEMPLATE_MARGIN_TOKENS = 64

ADD_TOOL = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers and return the sum.",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
}
TOOL_PROMPT = "Use the add tool to compute 17 + 25. Do not compute it yourself."
SUM_SCHEMA = {
    "type": "object",
    "properties": {"sum": {"type": "integer"}},
    "required": ["sum"],
    "additionalProperties": False,
}
ACTION_SYSTEM = (
    "You can use one tool: add(a: integer, b: integer) returns a + b. Reply with exactly "
    'one JSON object and nothing else. To call the tool: {"action": "tool", "name": '
    '"add", "args": {"a": <int>, "b": <int>}}. To give the final answer: '
    '{"action": "final", "result": {"sum": <int>}}.'
)


def _user(text: str) -> list[dict[str, Any]]:
    return [{"role": "user", "content": text}]


def _body(model_id: str, name: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "model": model_id,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if name == "auto":
        return base | {
            "messages": _user(TOOL_PROMPT),
            "max_tokens": 128,
            "tools": [ADD_TOOL],
            "tool_choice": "auto",
        }
    if name == "forced":
        return base | {
            "messages": _user(TOOL_PROMPT),
            "max_tokens": 128,
            "tools": [ADD_TOOL],
            "tool_choice": {"type": "function", "function": {"name": "add"}},
        }
    if name == "reasoning_on":
        return base | {
            "messages": _user(TOOL_PROMPT),
            "max_tokens": 512,
            "tools": [ADD_TOOL],
            "tool_choice": "auto",
            "chat_template_kwargs": {"enable_thinking": True},
        }
    if name == "with_schema":
        return base | {
            "messages": _user(TOOL_PROMPT + " Then answer as JSON with the sum."),
            "max_tokens": 128,
            "tools": [ADD_TOOL],
            "tool_choice": "auto",
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "sum_answer", "schema": SUM_SCHEMA, "strict": True},
            },
        }
    if name == "json_action":
        return base | {
            "messages": [
                {"role": "system", "content": ACTION_SYSTEM},
                {"role": "user", "content": "What is 17 + 25?"},
            ],
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
        }
    raise ValueError(name)


def _follow_up_body(model_id: str, call: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": model_id,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": 64,
        "tools": [ADD_TOOL],
        "messages": [
            *_user(TOOL_PROMPT),
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": call["arguments"]},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": "42"},
        ],
    }


def load_models() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    data = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    ids = {k: v for k, v in data["model_ids"].items() if not k.startswith("_")}
    return data["per_million_tokens"], ids


def worst_case_usd(body: dict[str, Any], price: dict[str, Any]) -> float:
    """Every request character as a token, plus a margin, plus max_tokens."""
    chars = len(json.dumps({k: body.get(k) for k in ("messages", "tools", "response_format")}))
    return (
        (chars + TEMPLATE_MARGIN_TOKENS) * price["input"] + body["max_tokens"] * price["output"]
    ) / 1_000_000


def usage_usd(usage: dict[str, Any], price: dict[str, Any]) -> float:
    """Cost formula from docs/ARCHITECTURE.md (completion tokens include reasoning)."""
    return (
        (usage.get("prompt_tokens") or 0) * price["input"]
        + (usage.get("completion_tokens") or 0) * price["output"]
    ) / 1_000_000


def run_call(client: httpx.Client, body: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "request": body,
        "status_code": None,
        "error": None,
        "chunks": [],
        "done_seen": False,
    }
    started = time.perf_counter()
    try:
        with client.stream("POST", "chat/completions", json=body) as response:
            record["status_code"] = response.status_code
            if response.status_code != 200:
                record["error"] = response.read().decode("utf-8", "replace")[:3000]
                return record
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    record["done_seen"] = True
                    continue
                record["chunks"].append(json.loads(payload))
    except httpx.HTTPError as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["latency_s"] = round(time.perf_counter() - started, 3)
    return record


# ---------------------------------------------------------------------------
# Analysis: facts only from what was observed


def analyze(record: dict[str, Any]) -> dict[str, Any]:
    chunks = record["chunks"]
    fragments: list[dict[str, Any]] = []
    calls: dict[int, dict[str, Any]] = {}
    finish: list[str] = []
    content = ""
    reasoning_chars = 0
    for chunk in chunks:
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            content += delta.get("content") or ""
            reasoning_chars += max(
                len(delta.get("reasoning_content") or ""), len(delta.get("reasoning") or "")
            )
            for piece in delta.get("tool_calls") or []:
                function = piece.get("function") or {}
                fragments.append(
                    {
                        "keys": sorted(piece),
                        "index": piece.get("index"),
                        "id": piece.get("id"),
                        "type": piece.get("type"),
                        "name": function.get("name"),
                        "arguments": function.get("arguments"),
                    }
                )
                call = calls.setdefault(
                    piece.get("index", 0), {"id": None, "name": None, "arguments": ""}
                )
                call["id"] = call["id"] or piece.get("id")
                call["name"] = call["name"] or function.get("name")
                call["arguments"] += function.get("arguments") or ""
            if choice.get("finish_reason") is not None:
                finish.append(choice["finish_reason"])
    final = [c["usage"] for c in chunks if c.get("usage") and c.get("choices") == []]
    assembled = []
    for index in sorted(calls):
        call = calls[index]
        try:
            args = json.loads(call["arguments"]) if call["arguments"] else None
            parsed = True
        except json.JSONDecodeError:
            args, parsed = None, False
        assembled.append({**call, "index": index, "args": args, "args_parsed": parsed})
    content_json = None
    try:
        content_json = json.loads(content) if content.strip() else None
    except json.JSONDecodeError:
        content_json = "unparsable"
    return {
        "status_code": record["status_code"],
        "error": record["error"],
        "fragments": fragments,
        "calls": assembled,
        "finish_reasons": finish,
        "content": content,
        "content_json": content_json,
        "reasoning_chars": reasoning_chars,
        "usage": final[-1] if final else None,
        "done_seen": record["done_seen"],
    }


# ---------------------------------------------------------------------------
# Markdown


def _fmt(value: Any) -> str:
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def _short(text: str, width: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def _call_lines(name: str, facts: dict[str, Any] | None) -> list[str]:
    if facts is None:
        return [f"- UNVERIFIED (`{name}`): not run."]
    tag = f"VERIFIED (`{name}`)"
    if facts["status_code"] != 200:
        return [f"- {tag}: HTTP {facts['status_code']}: {_short(facts['error'] or '', 400)}"]
    lines = [f"- {tag}: HTTP 200; `finish_reason` {_fmt(facts['finish_reasons'])}."]
    if facts["calls"]:
        calls = [
            {k: c[k] for k in ("index", "id", "name", "args", "args_parsed")}
            for c in facts["calls"]
        ]
        lines.append(f"- {tag}: assembled tool calls {_fmt(calls)}.")
        shapes = [
            {k: f[k] for k in ("keys", "index", "id", "name", "arguments")}
            for f in facts["fragments"][:4]
        ]
        lines.append(
            f"- {tag}: {len(facts['fragments'])} `delta.tool_calls` fragment(s); first ones "
            f"{_fmt(shapes)}."
        )
    else:
        lines.append(f"- {tag}: no `delta.tool_calls` fragments.")
    if facts["content"]:
        lines.append(f"- {tag}: content {_fmt(_short(facts['content']))}.")
    if facts["reasoning_chars"]:
        lines.append(f"- {tag}: {facts['reasoning_chars']} reasoning characters.")
    if facts["usage"]:
        lines.append(f"- {tag}: final usage {_fmt(facts['usage'])}.")
    return lines


def build_markdown(
    today: str, results: dict[str, dict[str, Any]], spend: float, notes: list[str]
) -> str:
    lines = [
        f"## Tool-calling probe ({today})",
        "",
        "Observed with `scripts/tool_probe.py` (raw results in `runs/tool_probe.json`, "
        "gitignored), streaming with `include_usage`, one function tool `add(a, b)`. Calls "
        'per model: `auto` (`tool_choice: "auto"`, reasoning off), `forced` (`tool_choice` '
        "naming the function), `reasoning_on`, `with_schema` (tools plus a wrapped json_schema "
        "`response_format`), `follow_up` (the tool call and a `tool` message with the result, "
        "only after a tool call in `auto`) and `json_action` (no tools, the JSON action "
        "protocol with `response_format: json_object`). One sample each. Estimated spend: "
        f"USD {spend:.6f}.",
        "",
    ]
    lines += [f"- {n}" for n in notes]
    if notes:
        lines.append("")
    for alias, by_call in results.items():
        lines += [f"### {alias}", ""]
        for name in ("auto", "forced", "reasoning_on", "with_schema", "follow_up", "json_action"):
            lines += _call_lines(name, by_call.get(name))
        lines.append("")
    return "\n".join(lines)


def _unverified_section(today: str, reason: str) -> str:
    return (
        f"## Tool-calling probe ({today})\n\nLive part skipped: {reason}.\n\n"
        "- UNVERIFIED: whether `tools` and `tool_choice` are accepted, whether the models "
        "emit tool calls, the shape of streamed tool-call deltas, `finish_reason`, tools "
        "with reasoning on, tools with `response_format`, the follow-up turn, and "
        "`response_format: json_object` for the JSON action protocol.\n"
    )


# ---------------------------------------------------------------------------


def _append_docs(markdown: str) -> None:
    text = DOCS_PATH.read_text(encoding="utf-8").rstrip("\n")
    DOCS_PATH.write_text(text + "\n\n" + markdown.rstrip("\n") + "\n", encoding="utf-8")
    print(f"Appended the section to {DOCS_PATH.relative_to(REPO_ROOT)}.")


def _spend(record: dict[str, Any], price: dict[str, Any], reserve: float) -> float:
    final = [c["usage"] for c in record["chunks"] if c.get("usage") and c.get("choices") == []]
    if final:
        return usage_usd(final[-1], price)
    if record["status_code"] is not None and 400 <= record["status_code"] < 500:
        return 0.0
    return reserve


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--write-docs", action="store_true")
    parser.add_argument("--from-json", action="store_true")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("NEBIUS_API_KEY", "").strip()
    base_url = os.getenv("NEBIUS_BASE_URL", "").strip() or DEFAULT_BASE_URL
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    prices, model_ids = load_models()

    if args.from_json:
        raw = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        results = {
            a: {n: analyze(r) for n, r in raw["calls"].get(a, {}).items()} for a in model_ids
        }
        markdown = build_markdown(
            raw["started"][:10], results, raw["estimated_spend_usd"], raw.get("notes", [])
        )
        OUT_MD.write_text(markdown, encoding="utf-8")
        print(f"Rebuilt {OUT_MD.name}.")
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
    raw: dict[str, Any] = {
        "started": datetime.now(UTC).isoformat(),
        "max_usd": MAX_USD,
        "calls": {},
    }
    results: dict[str, dict[str, Any]] = {}
    timeout = httpx.Timeout(60.0, connect=10.0)
    headers = {"Authorization": f"Bearer {api_key}"}
    aborted = False
    with httpx.Client(base_url=base_url, headers=headers, timeout=timeout) as client:
        for alias, model_id in model_ids.items():
            raw["calls"][alias], results[alias] = {}, {}
            for name in (
                "auto",
                "forced",
                "reasoning_on",
                "with_schema",
                "follow_up",
                "json_action",
            ):
                if name == "follow_up":
                    first = results[alias].get("auto")
                    if not first or not first["calls"] or not first["calls"][0]["id"]:
                        continue
                    body = _follow_up_body(model_id, first["calls"][0])
                else:
                    body = _body(model_id, name)
                reserve = worst_case_usd(body, prices[alias])
                if spend + reserve > MAX_USD:
                    notes.append(
                        f"Aborted before {alias} `{name}`: USD {spend:.6f} spent, "
                        f"worst case USD {reserve:.6f}, cap USD {MAX_USD}."
                    )
                    print(notes[-1])
                    aborted = True
                    break
                record = run_call(client, body)
                spend += _spend(record, prices[alias], reserve)
                raw["calls"][alias][name] = record
                results[alias][name] = facts = analyze(record)
                print(
                    f"{alias:<24} {name:<13} status={facts['status_code']} "
                    f"calls={len(facts['calls'])} finish={facts['finish_reasons']} "
                    f"spend=USD {spend:.6f}"
                )
            if aborted:
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


if __name__ == "__main__":
    sys.exit(main())
