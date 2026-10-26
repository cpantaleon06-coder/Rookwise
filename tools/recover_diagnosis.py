"""Recover a recorded run's full diagnosis by replaying its cassette, offline.

report.json (scripts/run_incident.py) keeps the diagnosis's claim ids, texts and reason
codes, not the root cause text, the citations, root_cause_claim_ids, the remediation plan,
the empty sources or the original claim order. All of them are on the run's `TeamRun`,
which run_incident.py builds and then drops. A replay of the run's cassette rebuilds the
same `TeamRun` with no network: the replay transport fails on any request and no key is
loaded. This tool replays the run, keeps the `TeamRun`, checks that the replay is the
recorded run, and writes the missing fields to one sidecar file for
scripts/export_recorded_run.py (--diagnosis).

It lives in tools/, not scripts/, and edits nothing: the engine is frozen at `freeze-1`
(docs/DECISIONS.md, "Engine freeze"). A replay reproduces a run only on the code that
recorded it, so it runs with the Python environment of a checkout at that commit and
loads that checkout's scripts/run_incident.py and `rookwise` package:

    git worktree add --detach ../rookwise-replay 3a8879e
    (create its .venv, install it, and generate its corpus logs with scripts/gen_incidents.py)
    ../rookwise-replay/.venv/Scripts/python tools/recover_diagnosis.py inc-03 \
        --checkout ../rookwise-replay --cassette CASSETTE --recorded RUN_DIR --out FILE

It refuses to write when the replay differs from the recorded run: every event (without
its timestamps and mode), the spend, the prediction, the diagnosis section, the audit and
the score must equal the recorded events.json and report.json.

The sidecar holds the diagnosis fields, each claim's evidence check and the empty
sources: model output about the synthetic corpus and lines quoted from it. No prompt text,
request, header or key.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SIDECAR_VERSION = 1
# Report keys a replay must reproduce exactly (the rest are timings or file paths).
REPORT_KEYS = ("status", "partial", "spent_usd", "predicted_usd", "diagnosis", "audit", "score")


class RecoverError(Exception):
    pass


def _strip_times(value: Any) -> Any:
    """`value` without the keys that hold wall-clock times (`ts`) or the replay's mode."""
    if isinstance(value, dict):
        return {k: _strip_times(v) for k, v in value.items() if k not in ("ts", "mode")}
    if isinstance(value, list):
        return [_strip_times(v) for v in value]
    return value


def compare_events(replayed: list[dict[str, Any]], recorded: list[dict[str, Any]]) -> list[str]:
    """Differences between the replayed and the recorded events, timestamps and mode
    aside. Empty when the replay is the recorded run."""
    problems = []
    if len(replayed) != len(recorded):
        problems.append(f"{len(replayed)} events replayed, {len(recorded)} recorded")
    for new, old in zip(replayed, recorded, strict=False):
        if _strip_times(new) != _strip_times(old):
            problems.append(f"event {old.get('id')} ({old.get('type')}) differs")
            break
    return problems


def compare_reports(replayed: dict[str, Any], recorded: dict[str, Any]) -> list[str]:
    return [
        f"report {key} differs"
        for key in REPORT_KEYS
        if json.loads(json.dumps(replayed.get(key), default=str)) != recorded.get(key)
    ]


def extract(team: Any) -> dict[str, Any]:
    """The sidecar body from a `TeamRun`: the diagnosis, each claim's evidence check in
    the diagnosis's claim order, and the empty sources. Only named fields are copied."""
    diagnosis, evidence = team.diagnosis, team.evidence
    if diagnosis is None:
        return {"diagnosis": None, "evidence": None, "empty_sources": list(team.empty_sources)}
    results = {r.claim_id: r for r in evidence.claims} if evidence is not None else {}
    if [c.claim_id for c in diagnosis.claims] != list(results):
        raise RecoverError("the evidence check does not list the diagnosis's claims in order")
    return {
        "diagnosis": {
            "root_cause": diagnosis.root_cause,
            "category": diagnosis.category,
            "claims": [
                {
                    "claim_id": c.claim_id,
                    "text": c.text,
                    "citations": [
                        {
                            "source_id": s.source_id,
                            "line_start": s.line_start,
                            "line_end": s.line_end,
                            "quote": s.quote,
                        }
                        for s in c.citations
                    ],
                }
                for c in diagnosis.claims
            ],
            "root_cause_claim_ids": list(diagnosis.root_cause_claim_ids),
            "remediation_plan": [
                {"action": s.action, "why": s.why, "risk": s.risk, "reversible": s.reversible}
                for s in diagnosis.remediation_plan
            ],
        },
        "evidence": [
            {
                "claim_id": r.claim_id,
                "supported": r.supported,
                "reason": r.reason,
                "citation_reasons": [c.reason for c in r.citations],
            }
            for r in results.values()
        ],
        "empty_sources": list(team.empty_sources),
    }


def check_against_report(body: dict[str, Any], report: dict[str, Any]) -> list[str]:
    """The recovered claims must be the ones report.json split into supported and
    withdrawn, with the same texts and reasons."""
    found = report.get("diagnosis") or {}
    if body["diagnosis"] is None:
        return [] if not found.get("category") else ["the replay has no diagnosis"]
    problems = []
    texts = {c["claim_id"]: c["text"] for c in body["diagnosis"]["claims"]}
    checks = {e["claim_id"]: e for e in body["evidence"]}
    supported = [c["claim_id"] for c in found.get("supported_claims") or []]
    withdrawn = [c["claim_id"] for c in found.get("withdrawn_claims") or []]
    if [i for i in texts if checks[i]["supported"]] != supported:
        problems.append("supported claims differ from report.json")
    if [i for i in texts if not checks[i]["supported"]] != withdrawn:
        problems.append("withdrawn claims differ from report.json")
    for claim in (found.get("supported_claims") or []) + (found.get("withdrawn_claims") or []):
        if texts.get(claim["claim_id"]) != claim["text"]:
            problems.append(f"claim {claim['claim_id']} text differs from report.json")
    for claim in found.get("withdrawn_claims") or []:
        check = checks.get(claim["claim_id"], {})
        if (check.get("reason"), check.get("citation_reasons")) != (
            claim["reason"],
            claim["citation_reasons"],
        ):
            problems.append(f"claim {claim['claim_id']} reasons differ from report.json")
    if body["diagnosis"]["category"] != found.get("category"):
        problems.append("category differs from report.json")
    return problems


def _load_run_incident(checkout: Path):
    sys.path.insert(0, str(checkout))
    path = checkout / "scripts" / "run_incident.py"
    spec = importlib.util.spec_from_file_location("run_incident_at_commit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import rookwise  # noqa: PLC0415 (resolved by the checkout's environment)

    package = Path(rookwise.__file__).resolve()
    if checkout.resolve() not in package.parents:
        raise RecoverError(f"rookwise resolves to {package}, not to the checkout {checkout}")
    return module


def replay(
    checkout: Path, incident_id: str, cassette: Path, recorded: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
    """(report, events, TeamRun) of a replay with the checkout's code."""
    os.environ["HARNESS_MODE"] = "replay"
    module = _load_run_incident(checkout)
    kept: list[Any] = []
    build_report = module.build_report

    def keep_team(mode, incident, team, *args, **kwargs):
        kept.append(team)
        return build_report(mode, incident, team, *args, **kwargs)

    module.build_report = keep_team
    options = {
        "bundle": module.load_bundle(incident_id),
        "truth": module.load_ground_truth(incident_id),
        "run_usd": recorded["cap_usd"],
        "cassette": cassette,
        "stop_after": recorded.get("stop_after"),
        "configuration": recorded.get("configuration") or "a",
        **(recorded.get("director_options") or {}),
    }
    accepted = inspect.signature(module.run).parameters
    unknown = [k for k, v in options.items() if k not in accepted and v not in (None, "a")]
    if unknown:
        raise RecoverError(f"the checkout's run() does not take {unknown}")
    options = {k: v for k, v in options.items() if k in accepted}
    report, events, _ = asyncio.run(module.run("replay", incident_id, **options))
    if len(kept) != 1:
        raise RecoverError("the replay did not build exactly one report")
    return report, events, kept[0]


def _commit(checkout: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    dirty = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")


def recover(incident_id: str, checkout: Path, cassette: Path, recorded_dir: Path) -> dict[str, Any]:
    recorded_report = json.loads((recorded_dir / "report.json").read_text(encoding="utf-8"))
    recorded_events = json.loads((recorded_dir / "events.json").read_text(encoding="utf-8"))
    if recorded_report.get("incident_id") != incident_id:
        raise RecoverError(f"{recorded_dir} is a run of {recorded_report.get('incident_id')}")
    try:
        report, events, team = replay(checkout, incident_id, cassette, recorded_report)
    except RecoverError:
        raise
    except Exception as exc:  # a cassette miss means the checkout is not the run's commit
        raise RecoverError(
            f"the replay failed ({type(exc).__name__}); is the checkout at the commit that "
            f"recorded the run? {str(exc)[:200]}"
        ) from exc
    problems = compare_events(events, recorded_events) + compare_reports(report, recorded_report)
    body = extract(team)
    problems += check_against_report(body, recorded_report)
    if problems:
        raise RecoverError("the replay is not the recorded run: " + "; ".join(problems))
    return {
        "_recovered": {
            "version": SIDECAR_VERSION,
            "tool": "tools/recover_diagnosis.py",
            "incident_id": incident_id,
            "run_id": events[0]["run_id"],
            "commit": _commit(checkout),
            "cassette": cassette.name,
            "verified": {
                "events": len(events),
                "report_keys": list(REPORT_KEYS),
                "against": "/".join(recorded_dir.resolve().parts[-2:]),
            },
        },
        **body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("incident_id")
    parser.add_argument(
        "--checkout", type=Path, required=True, help="a checkout at the run's commit"
    )
    parser.add_argument("--cassette", type=Path, required=True)
    parser.add_argument("--recorded", type=Path, required=True, help="the recorded run folder")
    parser.add_argument("--out", type=Path, required=True, help="the sidecar file to write")
    args = parser.parse_args()
    try:
        sidecar = recover(args.incident_id, args.checkout, args.cassette, args.recorded)
    except RecoverError as exc:
        print(f"recover failed: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n", "utf-8")
    meta = sidecar["_recovered"]
    claims = len(sidecar["diagnosis"]["claims"]) if sidecar["diagnosis"] else 0
    print(json.dumps({**meta, "claims": claims, "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
