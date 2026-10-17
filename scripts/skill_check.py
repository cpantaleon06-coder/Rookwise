"""Measure the Nemotron-adapted skills in skills/ on Nebius Token Factory.

For each skill and each model its roles use (config/skills.json), the script makes 3 calls
WITH the skill in the system prompt and 3 WITHOUT it, on one small fixed input. Every call
runs with reasoning off (`chat_template_kwargs.enable_thinking=false`) and the wrapped
json_schema form, both observed to work on all four models (docs/HARNESS_RESEARCH.md).

prompt_tokens WITH minus prompt_tokens WITHOUT is the real token cost of the skill on that
model. Checks are deterministic only: the content parses as JSON, matches the schema, has a
non-empty answer, and finish_reason is not "length" (a failure). Outputs are saved for a
person to read; the script makes no quality claim.

Spend goes through the budget ledger (rookwise.ledger): every call reserves its worst case
first, prices come from config/prices.json, and the run aborts at USD 0.50. Raw results go
to runs/skill_check.json and runs/skill_check_outputs.md (runs/ is gitignored).

Usage:
    python scripts/skill_check.py                      # every skill
    python scripts/skill_check.py --skills debug,postmortem
    python scripts/skill_check.py --write-config       # also record the measurements in
                                                       # config/skills.json with a margin
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

from rookwise.ledger import CapReached, Caps, InMemoryLedger, Usage
from rookwise.money import ZERO_USD
from rookwise.skills import compose_system_prompt, load_config, load_skill, skill_sha256

REPO_ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = REPO_ROOT / "config" / "prices.json"
SKILLS_CONFIG = REPO_ROOT / "config" / "skills.json"
OUT_JSON = REPO_ROOT / "runs" / "skill_check.json"
OUT_MD = REPO_ROOT / "runs" / "skill_check_outputs.md"

REPEATS = 3
MAX_TOKENS = 800
MAX_USD = Decimal("0.50")
# Ceiling = measured tokens plus 20%, rounded up to a multiple of 50.
MARGIN = 1.2
ROUND_TO = 50
RUN_ID = "skill-check"

BASE_PROMPT = "You are a Rookwise operator. Complete the task. Return only a JSON object."
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"output": {"type": "string"}, "notes": {"type": "string"}},
    "required": ["output", "notes"],
    "additionalProperties": False,
}
RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "skill_check", "schema": OUTPUT_SCHEMA, "strict": True},
}

# One small fixed input per skill. Incident and business cases are simulated.
CASES = {
    "prose-style": (
        "Rewrite this paragraph for a simulated corner grocery: \"Here's the thing: we are "
        "really leaning into delivery. It's not just a service, it's a game-changer that "
        'will truly transform the landscape for everyone."'
    ),
    "minimal-code": (
        "Write a Python function parse_price(text) that turns strings like '$1,234.50' "
        "into a float and raises ValueError for anything else."
    ),
    "code-review": (
        "Review this Python change:\n"
        "def get_user(db, name):\n"
        "    return db.execute(f\"SELECT * FROM users WHERE name = '{name}'\").fetchall()"
    ),
    "testing-strategy": (
        "Propose a test plan for apply_discount(price, percent), which the checkout of a "
        "simulated web shop calls on every order."
    ),
    "debug": (
        "After a deploy that renamed the field 'price' to 'unit_price' in cart items, "
        "checkout fails with: KeyError: 'price' at the line "
        "total = sum(item['price'] for item in cart)."
    ),
    "deploy-checklist": (
        "Release 1.4 of a simulated web shop adds a database migration (a new nullable "
        "column) and a feature flag for a new checkout page."
    ),
    "incident-triage": (
        "Simulated alert: checkout API error rate at 12% since 14:05 UTC. Open incidents: "
        "INC-7 'Payments provider latency' (active). No severity was given."
    ),
    "status-update": (
        "Simulated incident INC-9. Since the last update the team rolled back release 2.3 "
        "at 14:40 UTC and checkout errors fell from 12% to 0.5%. Write the next update."
    ),
    "postmortem": (
        'Review this simulated postmortem excerpt: "Timeline: 14:05 errors started. '
        "14:40 rolled back. Root cause: Bob deployed a bad config. Action items: be more "
        'careful."'
    ),
}


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: str
    notes: str


def user_message(skill_id: str) -> str:
    return (
        f"{CASES[skill_id]}\n\nReturn only a JSON object that matches this schema, with your "
        f'answer in "output" (at most 150 words) and one line in "notes":\n'
        f"{json.dumps(OUTPUT_SCHEMA)}"
    )


def plan(config: dict[str, Any], only: set[str] | None) -> list[dict[str, Any]]:
    """One entry per (skill, model): the first role in config order that uses it there."""
    pairs: dict[tuple[str, str], str] = {}
    for role, spec in config["roles"].items():
        for skill_id in spec["skills"]:
            pairs.setdefault((skill_id, spec["model"]), role)
    return [
        {"skill": skill_id, "model": model, "role": role}
        for (skill_id, model), role in pairs.items()
        if only is None or skill_id in only
    ]


def measurement_prompts(
    config: dict[str, Any], pairs: list[dict[str, Any]]
) -> dict[tuple[str, str], str]:
    """The WITH-skill system prompt per (skill, model), built by the runtime composer.

    The ceilings are lifted here because measuring must not depend on the ceilings it
    resets; an edited skill falls back to an estimate that can pass its old ceiling.
    """
    unbounded = copy.deepcopy(config)
    for spec in unbounded["skills"].values():
        spec["max_tokens"] = sys.maxsize
    for spec in unbounded["roles"].values():
        spec["max_skill_tokens"] = sys.maxsize
    return {
        (p["skill"], p["model"]): compose_system_prompt(
            p["role"], BASE_PROMPT, config=unbounded
        ).text
        for p in pairs
    }


def check(content: str | None, finish_reason: str | None) -> dict[str, Any]:
    result = {"json_parsed": False, "schema_valid": False, "answer_non_empty": False}
    if content:
        try:
            data = json.loads(content)
            result["json_parsed"] = True
            answer = Answer.model_validate(data)
            result["schema_valid"] = True
            result["answer_non_empty"] = bool(answer.output.strip())
        except (json.JSONDecodeError, ValidationError):
            pass
    result["passed"] = (
        finish_reason != "length" and result["schema_valid"] and result["answer_non_empty"]
    )
    return result


def call(client: OpenAI, model_id: str, system: str, user: str) -> dict[str, Any]:
    record: dict[str, Any] = {"status_code": None, "error": None, "usage": None}
    started = time.perf_counter()
    try:
        raw = client.chat.completions.with_raw_response.create(
            model=model_id,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=RESPONSE_FORMAT,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        record["status_code"] = raw.status_code
        record["retry_after"] = raw.headers.get("retry-after")
        data = raw.parse().model_dump()
        choice = (data.get("choices") or [{}])[0]
        record.update(
            usage=data.get("usage") or {},
            finish_reason=choice.get("finish_reason"),
            content=(choice.get("message") or {}).get("content"),
        )
    except APIStatusError as exc:
        record.update(
            status_code=exc.status_code,
            error=str(exc),
            retry_after=exc.response.headers.get("retry-after"),
        )
    except APIConnectionError as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # keep going; the error is recorded
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["latency_s"] = round(time.perf_counter() - started, 2)
    return record


def usage_of(record: dict[str, Any]) -> Usage | None:
    usage = record.get("usage") or {}
    if usage.get("prompt_tokens") is None or usage.get("completion_tokens") is None:
        return None
    return Usage(
        input_tokens=usage["prompt_tokens"],
        output_tokens=usage["completion_tokens"],
        cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
        reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        or 0,
    )


def summarize(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for key in dict.fromkeys((c["skill"], c["model"]) for c in calls):
        group = [c for c in calls if (c["skill"], c["model"]) == key]
        by = {v: [c for c in group if c["variant"] == v] for v in ("with", "without")}
        prompt = {
            v: sorted({c["prompt_tokens"] for c in cs if c["prompt_tokens"] is not None})
            for v, cs in by.items()
        }
        delta = (
            max(prompt["with"]) - min(prompt["without"])
            if prompt["with"] and prompt["without"]
            else None
        )
        rows.append(
            {
                "skill": key[0],
                "model": key[1],
                "prompt_tokens_with": prompt["with"],
                "prompt_tokens_without": prompt["without"],
                "skill_prompt_tokens": delta,
                "completion_tokens": {
                    v: [c["completion_tokens"] for c in cs] for v, cs in by.items()
                },
                "median_latency_s": {
                    v: statistics.median(c["latency_s"] for c in cs) if cs else None
                    for v, cs in by.items()
                },
                "passed": {
                    v: sum(c["checks"].get("passed", False) for c in cs) for v, cs in by.items()
                },
                "calls": {v: len(cs) for v, cs in by.items()},
                "finish_reasons": sorted({str(c.get("finish_reason")) for c in group}),
                "errors": [c["error"] for c in group if c["error"]],
            }
        )
    return rows


def write_config(rows: list[dict[str, Any]], date: str) -> None:
    config = json.loads(SKILLS_CONFIG.read_text(encoding="utf-8"))
    for row in rows:
        if row["skill_prompt_tokens"] is None:
            continue
        spec = config["skills"][row["skill"]]
        spec.setdefault("measured_prompt_tokens", {})[row["model"]] = row["skill_prompt_tokens"]
        spec["measured_sha256"] = skill_sha256(load_skill(row["skill"]))
        spec["measured_on"] = date
    for spec in config["skills"].values():
        if spec.get("measured_prompt_tokens"):
            spec["max_tokens"] = _ceiling(max(spec["measured_prompt_tokens"].values()))
    for role in config["roles"].values():
        counts = [
            config["skills"][s].get("measured_prompt_tokens", {}).get(role["model"])
            for s in role["skills"]
        ]
        if all(c is not None for c in counts):
            role["max_skill_tokens"] = _ceiling(sum(counts))
    config["_note"] = (
        "Maps each role to its model (an alias from config/prices.json) and skill ids. "
        "measured_prompt_tokens is the prompt-token cost of each skill per model, measured "
        f"with scripts/skill_check.py on {date}; it applies only while measured_sha256 "
        "matches the skill text, otherwise the loader falls back to an ESTIMATE "
        f"(characters / 4). Ceilings are the measured values plus {round((MARGIN - 1) * 100)}%"
        f", rounded up to a multiple of {ROUND_TO}. The ITOps roles are placeholders until "
        "the ITOps and DevOps use case is final. A role that leads a level of the team "
        "hierarchy names it in `level` (director, manager or auditor; core/team); every other "
        "role is an operator role."
    )
    SKILLS_CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote measured values and ceilings to {SKILLS_CONFIG}")


def _ceiling(tokens: int) -> int:
    return math.ceil(tokens * MARGIN / ROUND_TO) * ROUND_TO


def write_outputs(results: dict[str, Any]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), "utf-8")
    lines = [
        f"# Skill check outputs ({results['started_at']})",
        "",
        "Saved for reading. The script checks JSON and schema only, not quality.",
        "",
    ]
    for c in results["calls"]:
        lines += [
            f"## {c['skill']} on {c['model']}, {c['variant']} skill, repeat {c['repeat']}",
            "",
            f"finish_reason: {c.get('finish_reason')}; checks: {c['checks']}",
            "",
            "```",
            str(c.get("content") or c.get("error")),
            "```",
            "",
        ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRaw results written to {OUT_JSON} and {OUT_MD}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skills", help="comma-separated skill ids (default: all)")
    parser.add_argument(
        "--write-config",
        action="store_true",
        help="record the measurements and ceilings in config/skills.json",
    )
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between calls")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("NEBIUS_API_KEY", "").strip()
    base_url = os.getenv("NEBIUS_BASE_URL", "").strip()
    if not api_key or not base_url:
        print("NEBIUS_API_KEY and NEBIUS_BASE_URL must be set in .env. Stopping.")
        return 1

    config = load_config()
    model_ids = json.loads(PRICES_PATH.read_text(encoding="utf-8"))["model_ids"]
    only = {s.strip() for s in args.skills.split(",")} if args.skills else None
    pairs = plan(config, only)
    prompts = measurement_prompts(config, pairs)  # before any call: fail before spending
    client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0, timeout=90.0)
    ledger = InMemoryLedger()
    ledger.open_run(RUN_ID, Caps(run_usd=MAX_USD))
    results: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "max_usd": MAX_USD,
        "max_tokens": MAX_TOKENS,
        "reasoning": "off (chat_template_kwargs.enable_thinking=false)",
        "response_format": RESPONSE_FORMAT,
        "base_prompt": BASE_PROMPT,
        "stopped_reason": None,
        "calls": [],
    }
    print(
        f"{len(pairs)} skill/model pairs x {REPEATS} repeats x 2 variants, "
        f"cap USD {MAX_USD} (API key loaded, not shown)\n"
    )
    try:
        for pair in pairs:
            skill_id, model, role = pair["skill"], pair["model"], pair["role"]
            level = "auditor" if role == "auditor" else "operator"
            with_skill = prompts[(skill_id, model)]
            user = user_message(skill_id)
            for repeat in range(1, REPEATS + 1):
                for variant, system in (("without", BASE_PROMPT), ("with", with_skill)):
                    est_input = (len(system) + len(user)) // 2 + 256
                    reservation = ledger.reserve(
                        RUN_ID,
                        level=level,
                        task_id=f"{skill_id}/{model}/{variant}/{repeat}",
                        model=model,
                        input_tokens=est_input,
                        max_output_tokens=MAX_TOKENS,
                        usd_predicted=ZERO_USD,
                        skills=[skill_id] if variant == "with" else [],
                    )
                    time.sleep(args.pause)
                    record = call(client, model_ids[model], system, user)
                    usage = usage_of(record)
                    status = record["status_code"]
                    if usage is not None:
                        ledger.charge(reservation, usage)
                    elif status is not None and 400 <= status < 500:
                        ledger.release(reservation)
                    else:  # unknown outcome: charge the worst case
                        ledger.charge(reservation, Usage(est_input, MAX_TOKENS))
                    u = record.get("usage") or {}
                    entry = {
                        **pair,
                        "variant": variant,
                        "repeat": repeat,
                        "model_id": model_ids[model],
                        "prompt_tokens": u.get("prompt_tokens"),
                        "completion_tokens": u.get("completion_tokens"),
                        "reasoning_tokens": (u.get("completion_tokens_details") or {}).get(
                            "reasoning_tokens"
                        ),
                        "finish_reason": record.get("finish_reason"),
                        "latency_s": record["latency_s"],
                        "status_code": status,
                        "error": record["error"],
                        "checks": check(record.get("content"), record.get("finish_reason")),
                        "content": record.get("content"),
                        "usage": u,
                    }
                    results["calls"].append(entry)
                    print(
                        f"  {skill_id:17} {model:23} {variant:7} #{repeat} "
                        f"prompt={entry['prompt_tokens']} compl={entry['completion_tokens']} "
                        f"finish={entry['finish_reason']} lat={entry['latency_s']}s "
                        f"pass={entry['checks']['passed']}"
                        + (f" ERR {status}: {str(record['error'])[:80]}" if record["error"] else "")
                    )
                    if status == 429:
                        time.sleep(min(float(record.get("retry_after") or 5), 60.0))
    except CapReached as exc:
        results["stopped_reason"] = str(exc)
        print(f"\nSTOPPED: {exc}")
    finally:
        report = ledger.report(RUN_ID)
        results["finished_at"] = datetime.now(UTC).isoformat()
        results["estimated_spend_usd"] = str(report.spent_usd)
        results["summary"] = summarize(results["calls"])
        write_outputs(results)

    print(
        f"\n{'skill':17} {'model':23} {'without':>9} {'with':>9} {'skill':>6}  pass w/wo  "
        f"compl with  compl without"
    )
    for row in results["summary"]:
        print(
            f"{row['skill']:17} {row['model']:23} {str(row['prompt_tokens_without']):>9} "
            f"{str(row['prompt_tokens_with']):>9} {str(row['skill_prompt_tokens']):>6}  "
            f"{row['passed']['with']}/{row['calls']['with']} "
            f"{row['passed']['without']}/{row['calls']['without']}   "
            f"{row['completion_tokens']['with']}  {row['completion_tokens']['without']}"
        )
    print(f"\nEstimated spend USD {results['estimated_spend_usd']} (cap {MAX_USD})")
    if args.write_config and results["stopped_reason"] is None:
        write_config(results["summary"], results["started_at"][:10])
    return 0


if __name__ == "__main__":
    sys.exit(main())
