"""One smoke run of the team hierarchy (core/team) on the SYNTHETIC scenario in
examples/team_smoke/, under the ledger's run cap (scenario.json, USD 0.25, or
`--run-usd`).

Modes:
- estimate: no network. The team runs against a scripted stub transport so every real
  prompt is built and reserved by the ledger. Prints the ledger's worst-case reservation
  per call and an expected cost under the output assumptions in STUB_OUTPUT_TOKENS.
- record: ONE LIVE run on Token Factory (needs NEBIUS_API_KEY in .env; costs credits).
  The cassette goes to runs/cassettes/team_smoke.json (gitignored), or to `--cassette
  PATH`; recording replaces that file on its first write.
- live: ONE LIVE run like record, with HARNESS_MODE=live: nothing is recorded, so it
  cannot be replayed.
- replay: replays that cassette (or `--cassette PATH`) with a transport that fails on
  any request, and checks that the events match the recorded ones.

Each mode writes runs/team_smoke/<mode>/: events.json (the contract events), calls.json
(one record per model call: level, model, seconds, usage, finish reason, retries, the
reserved and the predicted USD, the raw usage object the API sent) and report.json (the
run summary: real and predicted cost per role and per model, outcomes per role, the
number of `length` finishes, every audited citation with its quote and evidence reason,
and the full reply text of every attempt that ended in a validation or protocol error).
Nothing from .env is printed or written, and no request headers are kept.

Usage:
    python scripts/team_smoke.py estimate
    HARNESS_MODE=record python scripts/team_smoke.py record
    HARNESS_MODE=live python scripts/team_smoke.py live --run-usd 0.05
    HARNESS_MODE=replay python scripts/team_smoke.py replay
    HARNESS_MODE=record python scripts/team_smoke.py record --cassette runs/cassettes/x.json
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import math
import os
import sys
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # noqa: E402 (lets `rookwise` resolve from a checkout)

import rookwise.harness.sse as sse_module  # noqa: E402
from rookwise.evidence import EvidenceBundle  # noqa: E402
from rookwise.harness import Cassette, Harness, StreamInterrupted, load_config  # noqa: E402
from rookwise.ledger import Caps, InMemoryLedger  # noqa: E402
from rookwise.money import ZERO_USD, format_usd  # noqa: E402
from rookwise.runner import OperatorSpec  # noqa: E402
from rookwise.store import InMemoryStore  # noqa: E402
from rookwise.team import run_team  # noqa: E402
from rookwise.team.auditor import AUDITOR_PROMPT  # noqa: E402
from rookwise.team.config import load_team_roles  # noqa: E402
from rookwise.team.flow import (  # noqa: E402
    DIAGNOSIS_PROMPT,
    DIRECTOR_PROMPT,
    MANAGER_PROMPT,
    OPERATOR_PROMPT,
)

SCENARIO_DIR = REPO_ROOT / "examples" / "team_smoke"
CASSETTE = REPO_ROOT / "runs" / "cassettes" / "team_smoke.json"
OUT_DIR = REPO_ROOT / "runs" / "team_smoke"
# Output tokens the estimate stub reports per call: assumptions, not measurements.
STUB_OUTPUT_TOKENS = {
    "director": 800,
    "diagnosis": 800,
    "manager": 300,
    "operator": 900,
    "auditor": 600,
}
STUB_PLAN = [
    [("incident-triager", "app-log"), ("debugger", "runbook")],
    [("incident-triager", "app-log"), ("debugger", "app-log")],
]


def load_scenario() -> dict[str, Any]:
    scenario = json.loads((SCENARIO_DIR / "scenario.json").read_text("utf-8"))
    scenario["texts"] = {
        source_id: (SCENARIO_DIR / name).read_text("utf-8")
        for source_id, name in scenario["sources"].items()
    }
    return scenario


# -- estimate stub ------------------------------------------------------------------------


def _sse(text: str, prompt: int, completion: int) -> bytes:
    def chunk(choices, usage=None):
        body: dict[str, Any] = {"id": "chatcmpl-stub", "choices": choices}
        if usage is not None:
            body["usage"] = usage
        return json.dumps(body)

    payloads = [
        chunk([{"index": 0, "delta": {"role": "assistant", "content": ""}}]),
        chunk([{"index": 0, "delta": {"content": text}}]),
        chunk([{"index": 0, "delta": {}, "finish_reason": "stop"}]),
        chunk([], {"prompt_tokens": prompt, "completion_tokens": completion}),
    ]
    return ("".join(f"data: {p}\n\n" for p in payloads) + "data: [DONE]\n\n").encode()


def _stub_transport() -> httpx.MockTransport:
    routes = (
        ("director", DIRECTOR_PROMPT),
        ("diagnosis", DIAGNOSIS_PROMPT),
        ("manager", MANAGER_PROMPT),
        ("auditor", AUDITOR_PROMPT),
        ("operator", OPERATOR_PROMPT),
    )
    claim = {
        "claim_id": "c1",
        "text": "[stub] The pool size was cut from 50 to 5.",
        "citations": [
            {
                "source_id": "app-log",
                "line_start": 14,
                "line_end": 14,
                "quote": "db.pool.max_connections: 50 -> 5",
            }
        ],
    }
    outputs = {
        "director": {
            "summary": "[stub] A plan.",
            "blocks": [
                {
                    "goal": "[stub] A block.",
                    "tasks": [
                        {"role": r, "source_id": s, "instruction": "[stub] Do it."}
                        for r, s in tasks
                    ],
                }
                for tasks in STUB_PLAN
            ],
        },
        "manager": {"summary": "[stub] The block is done."},
        "operator": {"summary": "[stub] Findings.", "claims": [claim]},
        "auditor": {"verdict": "accepted", "checks": [{"criterion": "[stub]", "passed": True}]},
        "diagnosis": {
            "root_cause": "[stub] The pool size was cut from 50 to 5.",
            "category": "bad_config",
            "claims": [claim],
            "root_cause_claim_ids": ["c1"],
            "remediation_plan": [
                {
                    "action": "[stub] Restore the pool size.",
                    "why": "[stub] The cut caused the timeouts.",
                    "risk": "[stub] None known.",
                    "reversible": True,
                }
            ],
        },
    }

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        kind = next(kind for kind, prompt in routes if system.startswith(prompt))
        prompt = math.ceil(sum(len(m["content"] or "") for m in body["messages"]) / 4)
        text = json.dumps({"status": "ok", "output": outputs[kind], "notes": ""})
        return httpx.Response(
            200,
            content=_sse(text, prompt, STUB_OUTPUT_TOKENS[kind]),
            headers={"content-type": "text/event-stream"},
        )

    return httpx.MockTransport(handle)


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"replay made a network request to {request.url.host}")


# -- the run ------------------------------------------------------------------------------


async def run(
    mode: str,
    scenario: dict[str, Any],
    run_usd: str | None = None,
    cassette: Path = CASSETTE,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[dict[str, Any], list, list]:
    """One run. `cassette` is the file record writes and replay reads; `transport`
    replaces the network in record mode (tests only)."""
    run_id = scenario["run_id"]
    ledger = InMemoryLedger()
    ledger.open_run(run_id, Caps(run_usd=Decimal(run_usd or scenario["run_usd"])))
    config = load_config(env={"HARNESS_MODE": "live"} if mode == "estimate" else os.environ)
    if mode == "estimate":
        harness = Harness(
            ledger, config=config, api_key="offline-stub", transport=_stub_transport()
        )
    elif mode == "record":
        cassette.parent.mkdir(parents=True, exist_ok=True)
        harness = Harness(
            ledger, config=config, transport=transport, cassette=Cassette(cassette, "record")
        )
    elif mode == "live":
        harness = Harness(ledger, config=config)
    else:
        harness = Harness(
            ledger,
            config=config,
            api_key="",
            transport=httpx.MockTransport(_no_network),
            cassette=Cassette(cassette, "replay"),
        )

    calls: list[dict[str, Any]] = []
    raw_usages: list[dict[str, Any]] = []
    reservations: list[Any] = []

    # Diagnostics only: see each raw `usage` object and each reservation, unchanged.
    parse_usage = sse_module.parse_usage

    def capture_usage(raw):
        raw_usages.append(dict(raw))
        return parse_usage(raw)

    sse_module.parse_usage = capture_usage
    reserve = ledger.reserve

    def capture_reserve(*args, **kwargs):
        reservation = reserve(*args, **kwargs)
        reservations.append(reservation)
        return reservation

    ledger.reserve = capture_reserve  # type: ignore[method-assign]
    complete = harness.complete

    async def timed(request, cancel=None):
        raw_usages.clear()
        first = len(reservations)
        start = time.perf_counter()
        record: dict[str, Any] = {
            "level": request.level,
            "task_id": request.task_id,
            "model": request.model,
        }
        try:
            result = await complete(request, cancel)
        except Exception as error:  # a refused reservation (CapReached) or an API error
            record |= {"seconds": round(time.perf_counter() - start, 3), "raised": str(error)}
            # The tool loop counts an interrupted stream as a model call; nothing else that
            # raised was one.
            record["counted"] = isinstance(error, StreamInterrupted)
            calls.append(record)
            raise
        held = reservations[first:]
        errors = [e for e in result.events if e.type == "error"]
        record |= {
            "seconds": round(time.perf_counter() - start, 3),
            "finish_reason": result.finish_reason,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cached_tokens": result.usage.cached_tokens,
            "reasoning_tokens": result.usage.reasoning_tokens,
            "usage_estimated": result.usage_estimated,
            "usd": format_usd(result.usd),
            "reserved_usd": format_usd(held[0].usd) if held else None,
            "usd_predicted": format_usd(held[-1].usd_predicted) if held else None,
            "attempts": result.attempts,
            "errors": [
                {"kind": e.kind, "status_code": e.status_code, "message": e.message[:200]}
                for e in errors
            ],
            "content_chars": len(result.text),
            "reasoning_chars": len(result.reasoning),
            "reasoning_in_content": bool(result.reasoning.strip())
            and result.reasoning.strip() in result.text,
            "raw_usage": raw_usages[-1] if raw_usages else None,
            "counted": True,
            REPLY_TEXT: result.text,
        }
        calls.append(record)
        return result

    harness.complete = timed  # type: ignore[method-assign]
    catalog = [OperatorSpec.model_validate(entry) for entry in scenario["catalog"]]
    started = time.perf_counter()
    try:
        async with harness:
            team = await run_team(
                scenario["goal"],
                run_id=run_id,
                harness=harness,
                store=InMemoryStore(),
                catalog=catalog,
                evidence=EvidenceBundle(sources=scenario["texts"]),
                mode="recorded" if mode == "replay" else "live",
                context_sources=tuple(scenario.get("context_sources", ())),
            )
    finally:
        sse_module.parse_usage = parse_usage
    total_s = time.perf_counter() - started
    report = build_report(mode, scenario, team, ledger.report(run_id), calls, total_s, catalog)
    for call in calls:  # reply texts go to report.json only, for the failed attempts
        call.pop(REPLY_TEXT, None)
    return report, [e.model_dump(mode="json") for e in team.events], calls


# -- the report ---------------------------------------------------------------------------

REPLY_TEXT = "_reply_text"  # a call's full reply text, kept until the report is built


def _checked(report: Any) -> dict[tuple[str, int], Any]:
    checked = {}
    if report is not None:
        for claim in report.claims:
            for result in claim.citations:
                checked[(claim.claim_id, result.index)] = result
    return checked


def _status(reason: str | None) -> str:
    return "not_checked" if reason is None else ("verified" if reason == "ok" else "failed")


def citation_details(team: Any, events: list[Any]) -> list[dict[str, Any]]:
    """Every checked citation as the model wrote it, with the evidence check's reason:
    the completed operator tasks' claims (`agent` operator), then the director's diagnosis
    claims (`agent` director, with `withdrawn` true for a claim withdrawn under D3)."""
    model_of = {
        e.payload.agent.agent_id: e.payload.agent.model for e in events if e.type == "agent_hired"
    }
    checked = _checked(team.operator_evidence)
    details = []
    for block in team.blocks:
        for task in block.tasks:
            if task.findings is None:
                continue
            model = model_of.get(f"a-op-{task.assignments[-1]}") if task.assignments else None
            for claim in task.findings.claims:
                claim_id = f"{task.task_id}:{claim.claim_id}"
                for index, citation in enumerate(claim.citations):
                    result = checked.get((claim_id, index))
                    reason = result.reason if result is not None else None
                    details.append(
                        {
                            "agent": "operator",
                            "claim_id": claim_id,
                            "task_id": task.task_id,
                            "operator_id": task.operator_ids[-1],
                            "model": model,
                            "index": index,
                            "source_id": citation.source_id,
                            "line_start": citation.line_start,
                            "line_end": citation.line_end,
                            "quote": citation.quote,
                            "reason": reason,
                            "status": _status(reason),
                        }
                    )
    if team.diagnosis is not None:
        checked = _checked(team.evidence)
        withdrawn = {w.claim.claim_id for w in team.withdrawn_claims}
        for claim in team.diagnosis.claims:
            for index, citation in enumerate(claim.citations):
                result = checked.get((claim.claim_id, index))
                reason = result.reason if result is not None else None
                details.append(
                    {
                        "agent": "director",
                        "claim_id": claim.claim_id,
                        "task_id": "diagnosis",
                        "model": model_of.get("a-director"),
                        "index": index,
                        "source_id": citation.source_id,
                        "line_start": citation.line_start,
                        "line_end": citation.line_end,
                        "quote": citation.quote,
                        "reason": reason,
                        "status": _status(reason),
                        "withdrawn": claim.claim_id in withdrawn,
                    }
                )
    return details


def error_replies(
    attempts: list[tuple[str, Any]], calls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The full reply texts of every attempt that ended in a validation error or a
    protocol error. `attempts` are (agent_id, AttemptRecord) in event order; each takes
    its `model_calls` from the calls of its task, in the order they were made."""
    queues: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for call in calls:
        if call.get("counted"):
            queues[call["task_id"]].append(call)
    found = []
    for agent_id, attempt in attempts:
        queue = queues[attempt.task_id]
        own, queues[attempt.task_id] = queue[: attempt.model_calls], queue[attempt.model_calls :]
        validation = attempt.loop_status == "final" and bool(attempt.validation_errors)
        if not validation and attempt.loop_status != "protocol_error":
            continue
        found.append(
            {
                "agent_id": agent_id,
                "task_id": attempt.task_id,
                "attempt_index": attempt.attempt_index,
                "model": attempt.model,
                "kind": "validation_error" if validation else "protocol_error",
                "validation_errors": attempt.validation_errors,
                "detail": attempt.detail,
                "replies": [{"model": call["model"], "text": call.get(REPLY_TEXT)} for call in own],
            }
        )
    return found


def _label(attempts: list[Any]) -> str:
    if not attempts or not attempts[-1].ok:
        return "failed"
    if any(a.reason == "escalation" for a in attempts):
        return "ok_after_escalation"
    if len(attempts) == 1:
        return "first_pass_ok"
    return "ok_after_retry"


def _ratio(real: Decimal, predicted: Decimal) -> float | None:
    return None if predicted == 0 else float((real - predicted) / predicted)


def build_report(mode, scenario, team, report, calls, total_s, catalog) -> dict[str, Any]:
    events = team.events
    roles = load_team_roles()
    role_of_level = {"director": roles.director.role, "manager": roles.manager.role}
    role_of_level["auditor"] = roles.auditor.role
    assigned = {e.payload.task.task_id: e.payload for e in events if e.type == "task_assigned"}
    price = {spec.operator_id: spec.price_per_task_est_usd for spec in catalog}

    def role(level: str, task_id: str) -> str:
        return assigned[task_id].task.role if level == "operator" else role_of_level[level]

    by_role: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "usd_real": ZERO_USD,
            "ledger_pred": ZERO_USD,
        }
    )
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "usd": ZERO_USD,
            "usd_predicted": ZERO_USD,
        }
    )
    for entry in report.entries:
        row = by_role[role(entry.level, entry.task_id)]
        row["input_tokens"] += entry.input_tokens
        row["output_tokens"] += entry.output_tokens
        row["usd_real"] += entry.usd_real
        row["ledger_pred"] += entry.usd_predicted
        model = by_model[entry.model]
        model["calls"] += 1
        model["input_tokens"] += entry.input_tokens
        model["output_tokens"] += entry.output_tokens
        model["reasoning_tokens"] += entry.reasoning_tokens
        model["usd"] += entry.usd_real
        model["usd_predicted"] += entry.usd_predicted
    catalog_pred: dict[str, Decimal] = defaultdict(lambda: ZERO_USD)
    for payload in assigned.values():
        catalog_pred[payload.task.role] += price[payload.operator_id]

    seconds: dict[str, float] = defaultdict(float)
    for call in calls:
        seconds[call["level"]] += call["seconds"]

    attempts: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for e in events:
        if e.type == "attempt_recorded":
            attempts[(e.payload.agent_id, e.payload.attempt.task_id)].append(e.payload.attempt)
    labels = [
        {
            "agent_id": agent_id,
            "task_id": task_id,
            "label": _label(items),
            "attempts": [
                {"model": a.model, "reason": a.reason, "loop_status": a.loop_status, "ok": a.ok}
                | ({"errors": a.validation_errors} if a.validation_errors else {})
                for a in items
            ],
        }
        for (agent_id, task_id), items in attempts.items()
    ]
    outcomes_by_role: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in labels:
        level = next(
            (
                lv
                for lv in ("director", "manager", "auditor")
                if item["agent_id"].startswith(f"a-{lv}")
            ),
            "operator",
        )
        outcomes_by_role[role(level, item["task_id"])][item["label"]] += 1

    rc = scenario["root_cause"]
    supported = (
        {c.claim_id for c in team.operator_evidence.claims if c.supported}
        if team.operator_evidence
        else set()
    )
    claims, hits = [], []
    for block in team.blocks:
        for task in block.tasks:
            if task.findings is None:
                continue
            for claim in task.findings.claims:
                claim_id = f"{task.task_id}:{claim.claim_id}"
                cites = [f"{c.source_id}:{c.line_start}-{c.line_end}" for c in claim.citations]
                item = {
                    "claim_id": claim_id,
                    "supported": claim_id in supported,
                    "text": claim.text,
                }
                claims.append(item | {"citations": cites})
                if any(
                    c.source_id == rc["source_id"]
                    and any(c.line_start <= n <= c.line_end for n in rc["lines"])
                    for c in claim.citations
                ):
                    hits.append(item)

    def money(rows):
        return {
            k: {f: format_usd(v) if isinstance(v, Decimal) else v for f, v in r.items()}
            for k, r in rows.items()
        }

    return {
        "mode": mode,
        "status": team.status,
        "partial": team.partial,
        "notes": team.notes,
        "wall_clock_s": {"total": round(total_s, 2)} | {k: round(v, 2) for k, v in seconds.items()},
        "spent_usd": format_usd(report.spent_usd),
        "predicted_usd": format_usd(report.predicted_usd),
        "prediction_error": _ratio(report.spent_usd, report.predicted_usd),
        "cap_usd": format_usd(report.caps.run_usd),
        "under_cap": report.spent_usd <= report.caps.run_usd,
        "stops": [f"{s.scope}:{s.key}" for s in report.stops],
        "by_role": money(by_role),
        "catalog_prediction_by_operator_role": {k: format_usd(v) for k, v in catalog_pred.items()},
        "by_model": money(by_model),
        "prediction_error_by_model": {
            k: _ratio(v["usd"], v["usd_predicted"]) for k, v in by_model.items()
        },
        "outcomes_by_role": {k: dict(v) for k, v in outcomes_by_role.items()},
        "length_finishes": sum(c.get("finish_reason") == "length" for c in calls),
        "labels": labels,
        "plan": team.plan.model_dump() if team.plan else None,
        "blocks": [
            {
                "block_id": b.block_id,
                "status": b.status,
                "summary": b.summary,
                "tasks": [
                    {
                        "task_id": t.task_id,
                        "role": t.role,
                        "slice_id": t.slice.slice_id,
                        "status": t.status,
                        "operators": t.operator_ids,
                        "summary": t.findings.summary if t.findings else None,
                    }
                    for t in b.tasks
                ],
                "reason": b.reason,
            }
            for b in team.blocks
        ],
        "escalations": [e.payload.model_dump() for e in events if e.type == "escalation"],
        "budget_exhausted": [
            e.payload.model_dump(mode="json") for e in events if e.type == "budget_exhausted"
        ],
        "audit": team.audit.model_dump() if team.audit else None,
        "auditor_model_review_ran": any(e.level == "auditor" for e in report.entries),
        "citation_verified_rate": team.operator_evidence.citation_verified_rate
        if team.operator_evidence
        else None,
        "unsupported_claims": team.operator_evidence.unsupported_claims
        if team.operator_evidence
        else None,
        "diagnosis_status": team.diagnosis_status,
        "inconclusive_reason": team.inconclusive_reason,
        "claim_counts": dataclasses.asdict(team.claim_counts) if team.claim_counts else None,
        "withdrawn_claims": [
            {
                "claim_id": w.claim.claim_id,
                "text": w.claim.text,
                "reason": w.reason,
                "citation_reasons": list(w.citation_reasons),
            }
            for w in team.withdrawn_claims
        ],
        "claims": claims,
        "citations": citation_details(team, events),
        "error_replies": error_replies(
            [
                (e.payload.agent_id, e.payload.attempt)
                for e in events
                if e.type == "attempt_recorded"
            ],
            calls,
        ),
        "root_cause_claims": hits,
        "root_cause_found": any(h["supported"] for h in hits),
        "diagnosis": team.diagnosis.model_dump() if team.diagnosis else None,
        "unread_slices": [dataclasses.asdict(u) for u in team.unread_slices],
        "empty_sources": team.empty_sources,
        "calls": len(calls),
        "_ratio_note": "prediction error = (real - predicted) / predicted",
        "_catalog_prediction_errors": {
            k: _ratio(v["usd_real"], catalog_pred[k])
            for k, v in by_role.items()
            if k in catalog_pred
        },
    }


def _normalized(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Events without wall-clock fields (any `ts`) and without the envelope's mode."""

    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in ("ts", "mode")}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    return [strip(e) for e in events]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("mode", choices=("estimate", "record", "live", "replay"))
    parser.add_argument("--run-usd", help="the run cap in USD, instead of scenario.json's")
    parser.add_argument(
        "--cassette",
        type=Path,
        default=CASSETTE,
        help="the cassette file for record and replay (default runs/cassettes/team_smoke.json)",
    )
    args = parser.parse_args()
    cassette = args.cassette.resolve()
    sys.stdout.reconfigure(encoding="utf-8")  # model text is not always cp1252 (Windows)
    if args.run_usd is not None and not Decimal(args.run_usd) > 0:
        print("--run-usd must be a positive amount; nothing was run.")
        return 2
    if cassette != CASSETTE.resolve() and args.mode not in ("record", "replay"):
        print("--cassette is for record and replay only; nothing was run.")
        return 2
    if args.mode in ("record", "live"):
        if os.environ.get("HARNESS_MODE") != args.mode:
            print(f"Set HARNESS_MODE={args.mode} for the live run; nothing was run.")
            return 2
        load_dotenv(REPO_ROOT / ".env")
        if not os.environ.get("NEBIUS_API_KEY"):
            print("NEBIUS_API_KEY is not set in .env; nothing was run.")
            return 2
    if args.mode == "replay" and not cassette.exists():
        print(f"No cassette at {cassette}; record first.")
        return 2
    scenario = load_scenario()
    out = OUT_DIR / args.mode
    out.mkdir(parents=True, exist_ok=True)
    report, events, calls = asyncio.run(run(args.mode, scenario, args.run_usd, cassette))
    if args.mode == "replay":
        recorded = json.loads((OUT_DIR / "record" / "events.json").read_text("utf-8"))
        report["replay_matches_record"] = _normalized(events) == _normalized(recorded)
        report["replay_event_count"] = [len(events), len(recorded)]
    for name, data in (("report", report), ("events", events), ("calls", calls)):
        text = json.dumps(data, indent=2, default=str, ensure_ascii=False) + "\n"
        (out / f"{name}.json").write_text(text, "utf-8")
    print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
