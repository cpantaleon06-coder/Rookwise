"""Tavily probe: ONE real search, to check the request and response shape that
core/tools/tavily.py assumes.

It sends exactly the request the tool sends (`POST TAVILY_URL`, JSON body
`{"query", "max_results"}`, the key in an `Authorization: Bearer` header) with a
harmless query, records the status, the response keys, the keys of each result and any
usage or credit field, and runs the tool's own parsing on the reply. No price is
assumed. Raw results go to runs/tavily_probe.json (gitignored, without the key); the
summary, tagged VERIFIED or UNVERIFIED, to runs/tavily_probe.md and, with --write-docs,
to docs/HARNESS_RESEARCH.md. Without TAVILY_API_KEY the live part is skipped.

Usage:
    python scripts/tavily_probe.py [--write-docs]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # noqa: E402 (lets `rookwise` resolve from a checkout)

from rookwise.harness.loop import ToolContext  # noqa: E402
from rookwise.tools.tavily import TAVILY_URL, TavilySearch  # noqa: E402

DOCS_PATH = REPO_ROOT / "docs" / "HARNESS_RESEARCH.md"
OUT_JSON = REPO_ROOT / "runs" / "tavily_probe.json"
OUT_MD = REPO_ROOT / "runs" / "tavily_probe.md"
QUERY = "What is the capital of France?"
MAX_RESULTS = 3
USAGE_HINTS = ("usage", "credit", "cost", "billing", "quota")


def _fmt(value: Any) -> str:
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def _usage_fields(data: Any, prefix: str = "") -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if any(h in key.lower() for h in USAGE_HINTS):
                found[path] = value
            if isinstance(value, dict):
                found |= _usage_fields(value, path)
    return found


def _append_docs(markdown: str) -> None:
    text = DOCS_PATH.read_text(encoding="utf-8").rstrip("\n")
    DOCS_PATH.write_text(text + "\n\n" + markdown.rstrip("\n") + "\n", encoding="utf-8")
    print(f"Appended the section to {DOCS_PATH.relative_to(REPO_ROOT)}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--write-docs", action="store_true")
    args = parser.parse_args()
    load_dotenv(REPO_ROOT / ".env")
    key = os.getenv("TAVILY_API_KEY", "").strip()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    title = f"## Tavily probe ({today})"

    if not key:
        markdown = (
            f"{title}\n\nLive part skipped: TAVILY_API_KEY is not set.\n\n- UNVERIFIED: the "
            "request and response shape of Tavily search, and any usage or credit field.\n"
        )
        OUT_MD.parent.mkdir(exist_ok=True)
        OUT_MD.write_text(markdown, encoding="utf-8")
        print("TAVILY_API_KEY is not set: live part skipped, every item UNVERIFIED.")
        if args.write_docs:
            _append_docs(markdown)
        return 0

    body = {"query": QUERY, "max_results": MAX_RESULTS}
    response = httpx.post(
        TAVILY_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=30.0
    )
    try:
        data: Any = response.json()
    except ValueError:
        data = {"_non_json_body": response.text[:2000]}
    results = data.get("results") if isinstance(data, dict) else None
    result_keys = sorted({k for r in results or [] if isinstance(r, dict) for k in r})
    usage = _usage_fields(data)

    # The tool's own parsing on the same reply, without a second request.
    def replay(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers={"content-type": "application/json"},
        )

    async def parse() -> Any:
        tool = TavilySearch("probe-replay", transport=httpx.MockTransport(replay))
        try:
            return await tool.search(dict(body), ToolContext("probe", "probe"))
        except Exception as error:  # recorded, not raised
            return {"_tool_error": f"{type(error).__name__}: {error}"}
        finally:
            await tool.aclose()

    parsed = asyncio.run(parse())
    record = {
        "started": datetime.now(UTC).isoformat(),
        "request": {"url": TAVILY_URL, "body": body, "auth": "Authorization: Bearer <key>"},
        "status_code": response.status_code,
        "response_headers": sorted(response.headers.keys()),
        "response": data,
        "tool_parsed": parsed,
    }
    OUT_JSON.parent.mkdir(exist_ok=True)
    text = json.dumps(record, indent=2, ensure_ascii=False)
    if key in text:
        raise SystemExit("refusing to write: the reply contains the key")
    OUT_JSON.write_text(text, encoding="utf-8")

    ok = response.status_code == 200 and isinstance(results, list)
    tool_ok = isinstance(parsed, dict) and "results" in parsed
    lines = [
        title,
        "",
        "Observed with `scripts/tavily_probe.py` (raw reply in `runs/tavily_probe.json`, "
        f"gitignored): one search, query {_fmt(QUERY)}, `max_results` {MAX_RESULTS}, sent "
        "exactly as `core/tools/tavily.py` sends it. One sample. Tavily bills by its own "
        "plan; no price is recorded.",
        "",
        f'- VERIFIED: `POST {TAVILY_URL}` with a JSON body `{{"query", "max_results"}}` and '
        f"`Authorization: Bearer <key>` returned HTTP {response.status_code}.",
    ]
    if ok:
        top = sorted(data) if isinstance(data, dict) else []
        lines += [
            f"- VERIFIED: response keys {_fmt(top)}.",
            f"- VERIFIED: {len(results)} results; keys per result {_fmt(result_keys)}.",
        ]
    else:
        lines.append(f"- VERIFIED: the reply was not a results list: {_fmt(data)[:500]}")
    if usage:
        lines.append(f"- VERIFIED: usage or credit fields in the reply {_fmt(usage)}.")
    else:
        lines.append(
            "- VERIFIED: the reply had no field named like usage, credit, cost, billing or "
            "quota. UNVERIFIED: credits used per search (check the Tavily dashboard)."
        )
    lines.append(
        f"- VERIFIED: the tool's parsing of this reply {'worked' if tool_ok else 'failed'}: "
        f"{_fmt(parsed)[:400]}"
    )
    markdown = "\n".join(lines) + "\n"
    OUT_MD.write_text(markdown, encoding="utf-8")
    print(markdown)
    if args.write_docs:
        _append_docs(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
