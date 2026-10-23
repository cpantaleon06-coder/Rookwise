"""Run one incident of the corpus (benchmarks/incidents/) through the hierarchy and score it.

The bundle comes from `rookwise.incidents.load_bundle` (the ground truth is never part of
it); ticket.md and runbook.md are the director's context sources (config/benchmark.json).
The diagnosis is scored with `rookwise.benchmark.score_run` against the ground truth, which
no model ever sees. The run cap defaults to the hierarchy's per-incident cap in
config/benchmark.json (D2: USD 0.10).

Modes:
- estimate: no network. A stub transport plays every agent. It reports, for each request,
  the calibrated input estimate as its prompt tokens, and output tokens sized from the
  second smoke record run (runs/cassettes/team_smoke.run2.json: the mean operator output;
  the director's plan and the managers' outputs too). A role the recording does not have
  gets 1,000 tokens, labeled as a placeholder in the report. The ledger, the slicing and
  every budget rule run for real, so the report shows which calls the ledger refuses.
  `--empty-slices FRACTION` makes that share of the slices claim-free in the stub's
  replies (chosen by a hash of the slice id, so the same slices every time); a claim-free
  reply still reports the same output tokens, so its cost is not lowered.
- record: ONE LIVE run on Token Factory (costs credits; needs NEBIUS_API_KEY in .env and
  HARNESS_MODE=record). It refuses to start unless --approve-cap equals --run-usd.
- replay: replays a recorded cassette with a transport that fails on any request.

`--plan-response-format json_schema` sends the director's plan call with the plan's schema
(inlined) as a wrapped json_schema response_format, and `--repair-temperature X` sets the
director's temperature from its first re-prompt on. Both are off by default
(config/skills.json, director role) and set only for this run; the report shows the
values the run used.

`--stop-after plan` ends the run once the director's plan is valid (in any mode): no other
agent is called, so a record run costs the plan call only (with its re-prompts, repairs
and escalations). The run finishes as `cancelled` and partial.

Each mode writes runs/incidents/<id>/<mode>/ (<mode>-plan/ with `--stop-after plan`, so a
full run's reports are not overwritten): report.json, events.json and calls.json.
Nothing from .env and no request header is printed or written.

Usage:
    python scripts/run_incident.py inc-01 estimate
    python scripts/run_incident.py inc-01 estimate --run-usd 0.50
    python scripts/run_incident.py inc-01 estimate --empty-slices 0.8
    HARNESS_MODE=record python scripts/run_incident.py inc-01 record --approve-cap 0.10
    python scripts/run_incident.py inc-01 estimate --stop-after plan
    HARNESS_MODE=replay python scripts/run_incident.py inc-01 replay
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import dataclasses
import json
import os
import re
import statistics
import sys
import time
import zlib
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # noqa: E402 (lets `rookwise` resolve from a checkout)

from rookwise.benchmark import score_run  # noqa: E402
from rookwise.evidence import EvidenceBundle, split_lines  # noqa: E402
from rookwise.harness import Cassette, Harness, StreamInterrupted, load_config  # noqa: E402
from rookwise.harness.request import build_request, estimate_input_tokens  # noqa: E402
from rookwise.incidents import GroundTruth, load_bundle, load_ground_truth  # noqa: E402
from rookwise.ledger import Caps, InMemoryLedger  # noqa: E402
from rookwise.money import format_usd  # noqa: E402
from rookwise.runner import OperatorSpec  # noqa: E402
from rookwise.skills import load_config as load_skills_config  # noqa: E402
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

CONFIG_PATH = REPO_ROOT / "config" / "benchmark.json"
OUT_DIR = REPO_ROOT / "runs" / "incidents"
RECORDED_RUN = REPO_ROOT / "runs" / "cassettes" / "team_smoke.run2.json"
PLACEHOLDER_TOKENS = 1000
ROUTES = (
    ("diagnosis", DIAGNOSIS_PROMPT),
    ("director", DIRECTOR_PROMPT),
    ("manager", MANAGER_PROMPT),
    ("auditor", AUDITOR_PROMPT),
    ("operator", OPERATOR_PROMPT),
)
# The prompts of the recorded run started like this, by role.
RECORDED_ROLES = (
    ("operator", "You are an operator"),
    ("director", "You are the director"),
    ("manager", "You are a manager"),
    ("auditor", "You are the independent auditor"),
)
SLICE_HEADER = re.compile(r"Source (\S+), lines (\d+)-(\d+) of (\d+) ")


def load_benchmark_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def default_cap(config: dict[str, Any]) -> str:
    return config["caps_usd"]["hierarchy"]


def cassette_path(incident_id: str) -> Path:
    return REPO_ROOT / "runs" / "cassettes" / f"incident-{incident_id}.json"


# -- the estimate stub -------------------------------------------------------------------


def stub_output_tokens(recorded: Path | None = None) -> dict[str, Any]:
    """Output tokens the stub reports per kind of call, and where each number comes from.
    The recording has no diagnosis call (it predates it): that one is a placeholder."""
    recorded = recorded or RECORDED_RUN
    sizes: dict[str, list[int]] = defaultdict(list)
    if recorded.exists():
        data = json.loads(recorded.read_text(encoding="utf-8"))
        for item in data["interactions"]:
            if item.get("kind") == "tool" or not item.get("usage"):
                continue
            system = item["request"]["messages"][0]["content"]
            kind = next((k for k, p in RECORDED_ROLES if system.startswith(p)), None)
            if kind is not None:
                sizes[kind].append(item["usage"]["output_tokens"])
    tokens: dict[str, int] = {}
    source: dict[str, str] = {}
    for kind, _ in ROUTES:
        values = sizes.get(kind) if kind != "diagnosis" else None
        if values:
            tokens[kind] = round(statistics.mean(values))
            source[kind] = f"mean of {len(values)} calls in {recorded.name}"
        else:
            tokens[kind] = PLACEHOLDER_TOKENS
            source[kind] = (
                f"PLACEHOLDER: {recorded.name} not found"
                if not recorded.exists()
                else f"PLACEHOLDER: no {kind} call in {recorded.name}"
            )
    operator = sizes.get("operator", [])
    return {
        "tokens": tokens,
        "source": source,
        "operator_mean": round(statistics.mean(operator)) if operator else None,
        "operator_max": max(operator) if operator else None,
    }


def _role_of(source_id: str) -> str:
    if source_id.endswith(".csv"):
        return "metrics-reader"
    if source_id.endswith(".diff"):
        return "deploy-diff-reader"
    return "log-reader"


def stub_plan(bundle: EvidenceBundle, context_sources: list[str]) -> dict[str, Any]:
    """A plan like a director's: the logs in one block, metrics and the diff in another,
    the context sources in a third. Every non-empty source is read."""
    groups: list[list[str]] = [[], [], []]
    for source_id, text in bundle.sources.items():
        if not split_lines(text):
            continue
        if source_id in context_sources:
            groups[2].append(source_id)
        elif source_id.endswith((".csv", ".diff")):
            groups[1].append(source_id)
        else:
            groups[0].append(source_id)
    blocks = []
    for group in groups:
        for start in range(0, len(group), 5):
            tasks = [
                {
                    "role": _role_of(s),
                    "source_id": s,
                    "instruction": "[stub] Read this slice and report what it shows.",
                }
                for s in group[start : start + 5]
            ]
            blocks.append({"goal": "[stub] Read these sources.", "tasks": tasks})
    return {"summary": "[stub] A plan.", "blocks": blocks}


def _first_line(bundle: EvidenceBundle, source_id: str, first: int, last: int) -> int:
    lines = split_lines(bundle.sources[source_id])
    return next((n for n in range(first, last + 1) if lines[n - 1].strip()), first)


def _citation(bundle: EvidenceBundle, source_id: str, number: int) -> dict[str, Any]:
    line = split_lines(bundle.sources[source_id])[number - 1]
    return {"source_id": source_id, "line_start": number, "line_end": number, "quote": line}


def is_empty_slice(slice_id: str, fraction: float) -> bool:
    """Whether the stub's reply for this slice has no claim: a stable hash of the slice
    id, so about `fraction` of the slices, and the same ones on every run."""
    return zlib.crc32(slice_id.encode("utf-8")) % 10_000 < round(fraction * 10_000)


def stub_transport(
    bundle: EvidenceBundle,
    context_sources: list[str],
    sizes: dict[str, int],
    config: Any,
    empty_fraction: float = 0.0,
) -> httpx.MockTransport:
    """Plays every agent with valid, neutral output. It never reads the ground truth."""
    cite_source = next(iter(context_sources), next(iter(bundle.sources)))

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        messages = body["messages"]
        kind = next(k for k, p in ROUTES if messages[0]["content"].startswith(p))
        user = messages[-1]["content"] if messages[-1]["role"] == "user" else ""
        if kind == "director":
            output = stub_plan(bundle, context_sources)
        elif kind == "operator":
            match = SLICE_HEADER.search(user)
            claims = []
            slice_id = f"{match.group(1)}:{match.group(2)}-{match.group(3)}" if match else ""
            if match and not is_empty_slice(slice_id, empty_fraction):
                source_id, first, last = match.group(1), int(match.group(2)), int(match.group(3))
                number = _first_line(bundle, source_id, first, last)
                claims = [
                    {
                        "claim_id": "c1",
                        "text": "[stub] The slice starts here.",
                        "citations": [_citation(bundle, source_id, number)],
                    }
                ]
            output = {"summary": "[stub] Findings.", "claims": claims}
        elif kind == "manager":
            output = {"summary": "[stub] The block is done."}
        elif kind == "diagnosis":
            number = _first_line(
                bundle, cite_source, 1, len(split_lines(bundle.sources[cite_source]))
            )
            output = {
                "root_cause": "[stub] A placeholder root cause.",
                "category": "bad_config",
                "claims": [
                    {
                        "claim_id": "d1",
                        "text": "[stub] The ticket says so.",
                        "citations": [_citation(bundle, cite_source, number)],
                    }
                ],
                "root_cause_claim_ids": ["d1"],
                "remediation_plan": [
                    {
                        "action": "[stub] Review the change.",
                        "why": "[stub] Placeholder.",
                        "risk": "[stub] None known.",
                        "reversible": True,
                    }
                ],
            }
        else:
            output = {"verdict": "accepted", "checks": [{"criterion": "[stub]", "passed": True}]}
        text = json.dumps({"status": "ok", "output": output, "notes": ""})
        prompt = estimate_input_tokens(
            messages,
            body.get("response_format") or body.get("tools"),
            config.chars_per_token,
            config.margin_tokens,
        )
        return httpx.Response(
            200,
            content=_sse(text, prompt, sizes[kind]),
            headers={"content-type": "text/event-stream"},
        )

    return httpx.MockTransport(handle)


def _sse(text: str, prompt: int, completion: int) -> bytes:
    def chunk(choices: list[Any], usage: dict[str, int] | None = None) -> str:
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


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"replay made a network request to {request.url.host}")


# -- the run -----------------------------------------------------------------------------


async def run(
    mode: str,
    incident_id: str,
    *,
    bundle: EvidenceBundle,
    truth: GroundTruth,
    run_usd: str,
    cassette: Path,
    config: dict[str, Any] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    empty_fraction: float = 0.0,
    stop_after: str | None = None,
    plan_response_format: str | None = None,
    repair_temperature: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """One run. `transport` replaces the network in record mode (tests only);
    `empty_fraction` is the estimate stub's share of claim-free slices; `stop_after`
    "plan" ends the run after the director's plan. `plan_response_format` and
    `repair_temperature` turn on the director's options for this run only (None keeps
    config/skills.json)."""
    config = config or load_benchmark_config()
    skills = director_options(load_skills_config(), plan_response_format, repair_temperature)
    director = load_team_roles(skills).director
    run_id = f"run_{incident_id.replace('-', '')}"
    ledger = InMemoryLedger()
    ledger.open_run(run_id, Caps(run_usd=Decimal(run_usd)))
    harness_config = load_config(env={"HARNESS_MODE": "live"} if mode == "estimate" else os.environ)
    context = [s for s in config["context_sources"] if s in bundle.sources]
    stub = None
    if mode == "estimate":
        stub = stub_output_tokens()
        harness = Harness(
            ledger,
            config=harness_config,
            api_key="offline-stub",
            transport=stub_transport(
                bundle, context, stub["tokens"], harness_config, empty_fraction
            ),
        )
    elif mode == "record":
        cassette.parent.mkdir(parents=True, exist_ok=True)
        harness = Harness(
            ledger,
            config=harness_config,
            transport=transport,
            cassette=Cassette(cassette, "record"),
        )
    else:
        harness = Harness(
            ledger,
            config=harness_config,
            api_key="",
            transport=httpx.MockTransport(_no_network),
            cassette=Cassette(cassette, "replay"),
        )

    calls: list[dict[str, Any]] = []
    complete = harness.complete

    async def timed(request, cancel=None):
        built = build_request(request, harness.config)
        record: dict[str, Any] = {
            "level": request.level,
            "task_id": request.task_id,
            "model": request.model,
            "input_tokens_estimate": built.input_tokens_estimate,
            "input_tokens_expected": built.predicted_input_tokens,
            "max_tokens": built.max_tokens,
        }
        start = time.perf_counter()
        try:
            result = await complete(request, cancel)
        except Exception as error:  # a refused reservation (CapReached) or an API error
            record |= {
                "seconds": round(time.perf_counter() - start, 3),
                "raised": str(error),
                "counted": isinstance(error, StreamInterrupted),
            }
            calls.append(record)
            raise
        record |= {
            "seconds": round(time.perf_counter() - start, 3),
            "finish_reason": result.finish_reason,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "usd": format_usd(result.usd),
            "attempts": result.attempts,
        }
        calls.append(record)
        return result

    harness.complete = timed  # type: ignore[method-assign]
    catalog = [OperatorSpec.model_validate(entry) for entry in config["catalog"]]
    started = time.perf_counter()
    async with harness:
        team = await run_team(
            config["goal"],
            run_id=run_id,
            harness=harness,
            store=InMemoryStore(),
            catalog=catalog,
            evidence=bundle,
            mode="recorded" if mode == "replay" else "live",
            context_sources=context,
            stop_after=stop_after,
            skills_config=skills,
        )
    total_s = time.perf_counter() - started
    scored = score_run(team, truth, bundle=bundle)
    report = build_report(mode, incident_id, team, ledger.report(run_id), calls, total_s, scored)
    report["stop_after"] = stop_after
    report["director_options"] = {
        "plan_response_format": director.plan_response_format,
        "repair_temperature": director.repair_temperature,
    }
    if stub is not None:
        report["stub_output_tokens"] = stub
        report["stub_empty_slices_fraction"] = empty_fraction
    return report, [e.model_dump(mode="json") for e in team.events], calls


def director_options(
    skills: dict[str, Any], plan_response_format: str | None, repair_temperature: float | None
) -> dict[str, Any]:
    """A copy of the skills config with the director's options set where given."""
    skills = copy.deepcopy(skills)
    (role,) = [r for r in skills["roles"].values() if r.get("level") == "director"]
    if plan_response_format is not None:
        role["plan_response_format"] = plan_response_format
    if repair_temperature is not None:
        role["repair_temperature"] = repair_temperature
    return skills


# -- the report --------------------------------------------------------------------------


def _ratio(real: Decimal, predicted: Decimal) -> float | None:
    return None if predicted == 0 else float((real - predicted) / predicted)


def _label(attempts: list[Any]) -> str:
    if not attempts or not attempts[-1].ok:
        return "failed"
    if any(a.reason == "escalation" for a in attempts):
        return "ok_after_escalation"
    return "first_pass_ok" if len(attempts) == 1 else "ok_after_retry"


def build_report(mode, incident_id, team, report, calls, total_s, scored) -> dict[str, Any]:
    events = team.events
    role_of_task = {
        e.payload.task.task_id: e.payload.task.role for e in events if e.type == "task_assigned"
    }
    attempts: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for e in events:
        if e.type == "attempt_recorded":
            attempts[(e.payload.agent_id, e.payload.attempt.task_id)].append(e.payload.attempt)
    outcomes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for (agent_id, task_id), items in attempts.items():
        if agent_id == "a-director":
            role = "director (diagnosis)" if task_id.startswith("diagnosis") else "director"
        elif agent_id.startswith("a-manager"):
            role = "manager"
        elif agent_id == "a-auditor":
            role = "auditor"
        else:
            role = role_of_task.get(task_id, "operator")
        outcomes[role][_label(items)] += 1
    refusals = [
        {
            "agent_id": p.agent_id,
            "level": p.level,
            "scope": p.scope,
            "key": p.key,
            "requested_usd": format_usd(p.requested_usd),
            "allocation_usd": format_usd(p.cap_usd),
            "left_usd": format_usd(p.cap_usd - p.committed_usd),
        }
        for p in (e.payload for e in events if e.type == "budget_exhausted")
    ]
    tasks = [t for b in team.blocks for t in b.tasks]
    operator_calls = [c for c in calls if c["level"] == "operator" and "raised" not in c]
    director_requests = {
        c["task_id"]: {
            "input_tokens_estimate": c["input_tokens_estimate"],
            "input_tokens_expected": c["input_tokens_expected"],
        }
        for c in calls
        if c["level"] == "director"
    }
    s = scored.score
    return {
        "incident_id": incident_id,
        "mode": mode,
        "status": team.status,
        "partial": team.partial,
        "notes": team.notes,
        "wall_clock_s": round(total_s, 2),
        "cap_usd": format_usd(report.caps.run_usd),
        "spent_usd": format_usd(report.spent_usd),
        "predicted_usd": format_usd(report.predicted_usd),
        "prediction_error": _ratio(report.spent_usd, report.predicted_usd),
        "under_cap": report.spent_usd <= report.caps.run_usd,
        "by_model": {
            m.model: {
                "calls": m.calls,
                "input_tokens": m.input_tokens,
                "output_tokens": m.output_tokens,
                "usd_real": format_usd(m.usd_real),
                "usd_predicted": format_usd(m.usd_predicted),
                "prediction_error": _ratio(m.usd_real, m.usd_predicted),
            }
            for m in report.by_model.values()
        },
        "calls": {
            "attempted": len(calls),
            "charged": sum("raised" not in c for c in calls),
            "refused_or_failed": sum("raised" in c for c in calls),
        },
        "ledger_refusals": refusals,
        "operator_calls_run": len(operator_calls),
        "operator_tasks": {
            "total": len(tasks),
            "ok": sum(t.status == "ok" for t in tasks),
            "failed": sum(t.status == "failed" for t in tasks),
            "not_run": sum(t.status == "not_run" for t in tasks),
        },
        "outcomes_by_role": {k: dict(v) for k, v in outcomes.items()},
        "unread_slices": [dataclasses.asdict(u) for u in team.unread_slices],
        # Operator replies whose complete part was salvaged from a cut or broken reply.
        "salvaged_replies": {
            "replies": sum(len(v) for v in team.salvaged_replies.values()),
            "dropped_elements": sum(sum(v) for v in team.salvaged_replies.values()),
            "by_task": {k: list(v) for k, v in team.salvaged_replies.items()},
        },
        # Operator citations whose source_id the team derived from the assigned slice.
        "citation_source_normalizations": {
            "total": sum(team.citation_source_normalizations.values()),
            "by_task": dict(team.citation_source_normalizations),
        },
        "managers": [
            {
                "block_id": b.block_id,
                "slices_read": b.slices_read,
                "empty_slices": b.empty_slices,
                "not_done": b.not_done,
                "batches": b.batches,
                "allocated_usd": format_usd(b.allocated_usd),
                "input_tokens_estimate": [
                    c["input_tokens_estimate"]
                    for c in calls
                    if c["level"] == "manager" and c["task_id"].startswith(f"{b.block_id}-summary")
                ],
            }
            for b in team.blocks
        ],
        "director_requests": director_requests,
        "diagnosis": {
            "status": team.diagnosis_status,
            "inconclusive_reason": team.inconclusive_reason,
            "category": team.diagnosis.category if team.diagnosis else None,
            "repairs": team.diagnosis_repairs,
            "supported_claims": [
                {"claim_id": c.claim_id, "text": c.text} for c in team.supported_claims
            ],
            "withdrawn_claims": [
                {
                    "claim_id": w.claim.claim_id,
                    "text": w.claim.text,
                    "reason": w.reason,
                    "citation_reasons": list(w.citation_reasons),
                }
                for w in team.withdrawn_claims
            ],
            "claim_counts": dataclasses.asdict(team.claim_counts) if team.claim_counts else None,
        },
        "audit": team.audit.model_dump() if team.audit else None,
        "score": {
            "diagnosis_correct": s.diagnosis_correct,
            "category_correct": s.category_correct,
            "evidence_recall": s.evidence_recall,
            "citation_verified_rate": s.citation_verified_rate,
            "citation_first_pass": {
                "valid": scored.first_pass_valid,
                "total": scored.first_pass_citations,
                "validity": scored.citation_first_pass_validity,
            },
            "citation_repairs": scored.citation_repairs,
            "withdrawn_claims": scored.withdrawn_claims,
        },
    }


# -- the command line --------------------------------------------------------------------


def _usd(value: str) -> Decimal | None:
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def main(argv: list[str] | None = None) -> int:
    config = load_benchmark_config()
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("incident_id")
    parser.add_argument("mode", choices=("estimate", "record", "replay"))
    parser.add_argument(
        "--run-usd", default=default_cap(config), help="the run cap (default: the hierarchy's)"
    )
    parser.add_argument("--cassette", type=Path, help="default runs/cassettes/incident-<id>.json")
    parser.add_argument(
        "--approve-cap", help="record only: must equal --run-usd, or nothing is run"
    )
    parser.add_argument(
        "--empty-slices",
        type=float,
        default=0.0,
        metavar="FRACTION",
        help="estimate only: the share of slices whose stub reply has no claim",
    )
    parser.add_argument(
        "--stop-after",
        choices=("plan",),
        help="end the run after the director's plan (a record run then costs the plan call)",
    )
    parser.add_argument(
        "--plan-response-format",
        choices=("json_schema",),
        help="send the director's plan call with the plan's schema as response_format",
    )
    parser.add_argument(
        "--repair-temperature",
        type=float,
        metavar="X",
        help="the director's temperature from its first re-prompt on (0 to 2)",
    )
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # model text is not always cp1252 (Windows)
    run_usd = _usd(args.run_usd)
    if run_usd is None:
        print("--run-usd must be a positive amount; nothing was run.")
        return 2
    cassette = (args.cassette or cassette_path(args.incident_id)).resolve()
    if args.mode == "record":
        approved = _usd(args.approve_cap) if args.approve_cap is not None else None
        if approved is None or approved != run_usd:
            print(
                f"Record mode makes live calls: pass --approve-cap {args.run_usd} to approve "
                "a run capped at that amount; nothing was run."
            )
            return 2
        if os.environ.get("HARNESS_MODE") != "record":
            print("Set HARNESS_MODE=record for the live run; nothing was run.")
            return 2
        load_dotenv(REPO_ROOT / ".env")
        if not os.environ.get("NEBIUS_API_KEY"):
            print("NEBIUS_API_KEY is not set in .env; nothing was run.")
            return 2
    elif args.approve_cap is not None:
        print("--approve-cap is for record mode only; nothing was run.")
        return 2
    if not 0.0 <= args.empty_slices <= 1.0:
        print("--empty-slices must be between 0 and 1; nothing was run.")
        return 2
    if args.repair_temperature is not None and not 0 <= args.repair_temperature <= 2:
        print("--repair-temperature must be between 0 and 2; nothing was run.")
        return 2
    if args.empty_slices and args.mode != "estimate":
        print("--empty-slices is for estimate mode only; nothing was run.")
        return 2
    if args.mode == "replay" and not cassette.exists():
        print(f"No cassette at {cassette}; record first.")
        return 2
    bundle = load_bundle(args.incident_id)
    truth = load_ground_truth(args.incident_id)  # for the score only; no model sees it
    report, events, calls = asyncio.run(
        run(
            args.mode,
            args.incident_id,
            bundle=bundle,
            truth=truth,
            run_usd=str(run_usd),
            cassette=cassette,
            config=config,
            empty_fraction=args.empty_slices,
            stop_after=args.stop_after,
            plan_response_format=args.plan_response_format,
            repair_temperature=args.repair_temperature,
        )
    )
    folder = f"{args.mode}-{args.stop_after}" if args.stop_after else args.mode
    out = OUT_DIR / args.incident_id / folder
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("report", report), ("events", events), ("calls", calls)):
        text = json.dumps(data, indent=2, default=str, ensure_ascii=False) + "\n"
        (out / f"{name}.json").write_text(text, "utf-8")
    print(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
