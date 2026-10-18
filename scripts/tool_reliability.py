"""Tool-calling reliability: the Stage 2 tool task, N times per model and protocol.

The task: "Use the add tool to compute 17 + 25, then give the final result as
{"sum": <int>}", run through the real harness tool loop (`rookwise.harness.ToolLoop`)
with one tool, `add(a, b)`, reasoning off, `max_tokens` 128 per step. Each model runs
it N times (default 15) with `native_tools` and N times with `json_protocol`.

A run succeeds when the loop ends with a final answer equal to `{"sum": 42}` and the
tool ran exactly once with `{"a": 17, "b": 25}`. Failures are counted by kind (loop
status, wrong or missing tool call, wrong answer).

Hard cap: the ledger's run cap of USD 0.10 (worst-case reservations included), so no
call is sent once the cap could be passed; the summary says how many runs completed.
Runs are interleaved (one of every model and protocol per round), so a stop leaves
every cell with a similar number of samples. Prices come only from config/prices.json.
Raw results go to runs/tool_reliability.json (gitignored), the summary to
runs/tool_reliability.md and, with --write-docs, to docs/HARNESS_RESEARCH.md. Without
NEBIUS_API_KEY the live part is skipped and every item is UNVERIFIED.

Usage:
    python scripts/tool_reliability.py [--reps 15] [--write-docs]
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # noqa: E402 (lets `rookwise` resolve from a checkout)

from rookwise.harness import Harness, Tool, ToolLoop, load_config  # noqa: E402
from rookwise.harness.request import ChatRequest  # noqa: E402
from rookwise.ledger import CapReached, Caps, InMemoryLedger  # noqa: E402

DOCS_PATH = REPO_ROOT / "docs" / "HARNESS_RESEARCH.md"
OUT_JSON = REPO_ROOT / "runs" / "tool_reliability.json"
OUT_MD = REPO_ROOT / "runs" / "tool_reliability.md"
MAX_USD = Decimal("0.10")
RUN_ID = "tool-reliability"
PROTOCOLS = ("native_tools", "json_protocol")
MESSAGES = [
    {"role": "system", "content": "You are a careful assistant that uses tools when asked."},
    {
        "role": "user",
        "content": "Use the add tool to compute 17 + 25. Do not compute it yourself. Then "
        'give the final result as {"sum": <int>}.',
    },
]
ADD_SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
    "required": ["a", "b"],
}


def make_add_tool(calls: list[dict[str, Any]]) -> Tool:
    async def add(args: dict[str, Any], _context: Any) -> int:
        calls.append(dict(args))
        return int(args["a"]) + int(args["b"])

    return Tool("add", "Add two integers and return the sum.", ADD_SCHEMA, add)


async def one_run(harness: Harness, model: str, protocol: str, index: int) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    loop = ToolLoop(harness, [make_add_tool(calls)])
    request = ChatRequest(
        model=model,
        messages=MESSAGES,
        run_id=RUN_ID,
        level="operator",
        task_id=f"{model}/{protocol}/{index}",
        max_tokens=128,
        reasoning=False,
    )
    outcome = await loop.run(request, protocol=protocol)  # type: ignore[arg-type]
    final_ok = outcome.status == "final" and outcome.final == {"sum": 42}
    tool_ok = calls == [{"a": 17, "b": 25}]
    if final_ok and tool_ok:
        kind = "ok"
    elif outcome.status != "final":
        kind = f"loop_{outcome.status}"
    elif not calls:
        kind = "final_without_tool"
    elif not tool_ok:
        kind = "wrong_tool_calls"
    else:
        kind = "wrong_final"
    protocol_errors = sum(1 for t in outcome.trace if t.get("kind") == "protocol_error")
    bad_tool_results = sum(1 for t in outcome.trace if t.get("kind") == "tool" and not t["ok"])
    return {
        "model": model,
        "protocol": protocol,
        "index": index,
        "kind": kind,
        "status": outcome.status,
        "final": outcome.final,
        "tool_args": calls,
        "steps": outcome.steps,
        "model_calls": outcome.model_calls,
        "length": dataclasses.asdict(outcome.length) if outcome.length else None,
        "protocol_errors": protocol_errors,
        "failed_tool_results": bad_tool_results,
        "usd": str(outcome.usd),
        "detail": outcome.detail[:300],
    }


def _fmt(value: Any) -> str:
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def build_markdown(
    today: str,
    runs: list[dict[str, Any]],
    reps: int,
    spend: Decimal,
    models: list[str],
    stopped: str | None,
) -> str:
    lines = [
        f"## Tool-calling reliability ({today})",
        "",
        "Observed with `scripts/tool_reliability.py` (raw results in "
        "`runs/tool_reliability.json`, gitignored): the Stage 2 tool task (use `add` for "
        '17 + 25, then answer `{"sum": 42}`) through the harness tool loop, reasoning off, '
        f"`max_tokens` 128 per step, {reps} runs planned per model and protocol, interleaved. "
        'A run succeeds when the final answer is `{"sum": 42}` and the tool ran exactly '
        f'once with `{{"a": 17, "b": 25}}`. Estimated spend (ledger): USD {spend:.6f}, '
        f"cap USD {MAX_USD}.",
        "",
    ]
    if stopped:
        lines += [f"- Stopped early: {stopped}.", ""]
    lines += [
        "| Model | Protocol | Successes | Failures by kind | Mean model calls |",
        "|---|---|---|---|---|",
    ]
    for model in models:
        for protocol in PROTOCOLS:
            cell = [r for r in runs if r["model"] == model and r["protocol"] == protocol]
            if not cell:
                lines.append(f"| {model} | {protocol} | not run | | |")
                continue
            ok = sum(r["kind"] == "ok" for r in cell)
            failures = Counter(r["kind"] for r in cell if r["kind"] != "ok")
            calls = sum(r["model_calls"] for r in cell) / len(cell)
            fail_text = ", ".join(f"{k} {v}" for k, v in sorted(failures.items())) or "none"
            lines.append(
                f"| {model} | {protocol} | {ok} / {len(cell)} ({100 * ok / len(cell):.0f}%) "
                f"| {fail_text} | {calls:.1f} |"
            )
    lines += [
        "",
        "- VERIFIED: the table above, for these runs only (one prompt, one tool, reasoning "
        "off). Rates from 15 runs are rough; they say nothing about other tasks or tools.",
        "- UNVERIFIED: reliability with reasoning on, several tools, parallel calls and long "
        "tool results.",
    ]
    return "\n".join(lines) + "\n"


def _append_docs(markdown: str) -> None:
    text = DOCS_PATH.read_text(encoding="utf-8").rstrip("\n")
    DOCS_PATH.write_text(text + "\n\n" + markdown.rstrip("\n") + "\n", encoding="utf-8")
    print(f"Appended the section to {DOCS_PATH.relative_to(REPO_ROOT)}.")


async def run_all(reps: int, models: list[str]) -> tuple[list[dict[str, Any]], float, str | None]:
    config = load_config(env={"NEBIUS_BASE_URL": os.getenv("NEBIUS_BASE_URL", "")})
    ledger = InMemoryLedger()
    ledger.open_run(RUN_ID, Caps(run_usd=MAX_USD))
    runs: list[dict[str, Any]] = []
    stopped = None
    async with Harness(ledger, config=config) as harness:
        for index in range(reps):
            jobs = [one_run(harness, m, p, index) for m in models for p in PROTOCOLS]
            results = await asyncio.gather(*jobs, return_exceptions=True)
            for result in results:
                if isinstance(result, CapReached):
                    stopped = f"ledger cap reached ({result})"
                elif isinstance(result, BaseException):
                    stopped = f"{type(result).__name__}: {result}"
                else:
                    runs.append(result)
                    if result["status"] == "budget_exhausted":
                        stopped = "ledger cap reached (a reservation was refused)"
            done = len(runs)
            print(
                f"round {index + 1}/{reps}: {done} runs, USD {ledger.report(RUN_ID).spent_usd:.6f}"
            )
            if stopped:
                break
    report = ledger.report(RUN_ID)
    assert report.held_usd == 0
    return runs, report.spent_usd, stopped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--reps", type=int, default=15)
    parser.add_argument("--write-docs", action="store_true")
    args = parser.parse_args()
    load_dotenv(REPO_ROOT / ".env")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if not os.getenv("NEBIUS_API_KEY", "").strip():
        markdown = (
            f"## Tool-calling reliability ({today})\n\nLive part skipped: NEBIUS_API_KEY is "
            "not set.\n\n- UNVERIFIED: success rates per model and protocol.\n"
        )
        OUT_MD.parent.mkdir(exist_ok=True)
        OUT_MD.write_text(markdown, encoding="utf-8")
        print("NEBIUS_API_KEY is not set: live part skipped, every item UNVERIFIED.")
        if args.write_docs:
            _append_docs(markdown)
        return 0
    models = list(load_config(env={}).models)
    runs, spend, stopped = asyncio.run(run_all(args.reps, models))
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(
            {
                "started": today,
                "reps": args.reps,
                "spend_usd": str(spend),
                "stopped": stopped,
                "runs": runs,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    markdown = build_markdown(today, runs, args.reps, spend, models, stopped)
    OUT_MD.write_text(markdown, encoding="utf-8")
    print(markdown)
    if args.write_docs:
        _append_docs(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
