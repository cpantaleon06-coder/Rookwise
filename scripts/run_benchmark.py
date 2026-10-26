"""Run the benchmark plan: every (incident, configuration, repeat), one after another.

The plan is `benchmark` in config/benchmark.json: the incidents, the configurations (a the
hierarchy, b and c the single-model baselines; see scripts/run_incident.py), the repeats
and each configuration's run cap. Each run is one `run_incident.run` in record mode.

Cost first: the script always runs estimate mode (no network, the stub transport of
scripts/run_incident.py) for every (incident, configuration) still to run and prints the
predicted total, with the worst case (the sum of the run caps). An estimate is the same
for every repeat, so it runs once per pair. Without `--live` it stops there. With `--live`
it refuses to start unless `--approve-total-usd` is given and at least the predicted total
of the runs still to do; it also stops before a run whose predicted cost would take this
invocation's spending past the approved total.

Resumable: a run whose result file exists is skipped, so an interrupted benchmark goes on
where it stopped. A result file is written only when its run finishes (atomically), and a
run that raises stops the benchmark with nothing written for it.

Never partially replayed: the dev-only cassette reuse of scripts/run_incident.py
(`--reuse-cassette`) is refused here, and a run whose report says it was partially
replayed stops the benchmark with nothing written for it.

Dev and test: an incident's split comes from its ground truth. Test-split incidents run
live only with `--freeze-confirmed`: tuning must end before any test run is made. Each
result file records the commit and a hash of the config files, and the summary reports
the test split apart from the dev split, warning when test results come from more than
one commit.

Outputs, under `results_dir` (benchmarks/results/): one metrics-only JSON file per run in
`runs/` (no prompt text, no model text: counts, costs and scores), then `summary-dev.csv`,
`summary-test.csv` (one row per configuration) and `summary.md`. Cassettes, which hold
prompt text, go to `cassette_dir` (runs/cassettes/benchmark/, gitignored). Nothing from
.env and no request header is printed or written.

`--repeats N` runs only repeats 1 to N of each (incident, configuration), N at most the
configured `repeats`; the others are not planned (a later run with a larger N adds them).

Usage:
    python scripts/run_benchmark.py
    python scripts/run_benchmark.py --split all
    python scripts/run_benchmark.py --repeats 1
    HARNESS_MODE=record python scripts/run_benchmark.py --live --approve-total-usd 5.00
    HARNESS_MODE=record python scripts/run_benchmark.py --live --approve-total-usd 9.00 \\
        --split test --freeze-confirmed
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent
sys.path.insert(0, str(REPO_ROOT))  # noqa: E402 (lets `rookwise` resolve from a checkout)
sys.path.insert(0, str(SCRIPTS))  # noqa: E402 (run_incident is a sibling script)

import run_incident  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from rookwise.evidence import EvidenceBundle  # noqa: E402
from rookwise.incidents import GroundTruth, load_bundle, load_ground_truth  # noqa: E402
from rookwise.money import ZERO_USD, format_usd  # noqa: E402

CONFIG_FILES = (
    "config/benchmark.json",
    "config/budget.json",
    "config/harness.json",
    "config/skills.json",
    "config/slicing.json",
    "config/prices.json",
)
SPLITS = ("dev", "test")

# What run_incident.run returns: (report, events, calls).
Runner = Callable[..., Awaitable[tuple[dict[str, Any], list[Any], list[dict[str, Any]]]]]
Loader = Callable[[str], tuple[EvidenceBundle, GroundTruth]]
TruthLoader = Callable[[str], GroundTruth]


@dataclass(frozen=True)
class PlannedRun:
    incident_id: str
    split: str
    configuration: str
    repeat: int
    cap_usd: Decimal

    @property
    def name(self) -> str:
        return f"{self.incident_id}__{self.configuration}__r{self.repeat}"


def load_plan(config: dict[str, Any]) -> dict[str, Any]:
    """The `benchmark` section of config/benchmark.json, checked."""
    plan = config["benchmark"]
    unknown = [c for c in plan["configurations"] if c not in run_incident.CONFIGURATIONS]
    if unknown:
        raise ValueError(f"unknown configurations {unknown}; use {run_incident.CONFIGURATIONS}")
    if int(plan["repeats"]) < 1:
        raise ValueError("repeats must be at least 1")
    for configuration in plan["configurations"]:
        if Decimal(cap_for(config, configuration)) <= 0:
            raise ValueError(f"the cap of configuration {configuration} must be positive")
    return plan


def cap_for(config: dict[str, Any], configuration: str) -> str:
    """The benchmark's cap for a configuration, else run_incident's default cap."""
    caps = config["benchmark"].get("caps_usd", {})
    return caps.get(configuration) or run_incident.default_cap(config, configuration)


def default_loader(incident_id: str) -> tuple[EvidenceBundle, GroundTruth]:
    return load_bundle(incident_id), load_ground_truth(incident_id)


def planned_runs(
    config: dict[str, Any],
    split: str,
    truth_loader: TruthLoader = load_ground_truth,
    repeats: int | None = None,
) -> list[PlannedRun]:
    """Every (incident, configuration, repeat) of the plan whose incident is in `split`
    ("dev", "test" or "all"), incident by incident. The split is the ground truth's.
    `repeats` (None: the configured number) keeps repeats 1 to `repeats` only; it must be
    between 1 and the configured number."""
    plan = load_plan(config)
    configured = int(plan["repeats"])
    if repeats is None:
        repeats = configured
    if not 1 <= repeats <= configured:
        raise ValueError(f"repeats must be between 1 and the configured {configured}")
    runs = []
    for incident_id in plan["incidents"]:
        truth = truth_loader(incident_id)
        if split != "all" and truth.split != split:
            continue
        for configuration in plan["configurations"]:
            for repeat in range(1, repeats + 1):
                cap = Decimal(cap_for(config, configuration))
                runs.append(PlannedRun(incident_id, truth.split, configuration, repeat, cap))
    return runs


def result_path(results_dir: Path, run: PlannedRun) -> Path:
    return results_dir / "runs" / f"{run.name}.json"


async def estimate(
    runs: list[PlannedRun],
    config: dict[str, Any],
    loader: Loader,
    runner: Runner,
    tmp_dir: Path,
) -> dict[tuple[str, str], Decimal]:
    """The estimate-mode cost of each (incident, configuration) among `runs`: what the
    stub run spent. No network."""
    costs: dict[tuple[str, str], Decimal] = {}
    for run in runs:
        key = (run.incident_id, run.configuration)
        if key in costs:
            continue
        bundle, truth = loader(run.incident_id)
        report, _, _ = await runner(
            "estimate",
            run.incident_id,
            bundle=bundle,
            truth=truth,
            run_usd=str(run.cap_usd),
            cassette=tmp_dir / "unused.json",
            config=config,
            configuration=run.configuration,
        )
        costs[key] = Decimal(report["spent_usd"])
    return costs


def metrics(report: dict[str, Any], run: PlannedRun, provenance: dict[str, Any]) -> dict[str, Any]:
    """A run's result file: counts, costs and scores only. No prompt, model or claim text
    (the report's notes, claims and audit stay out)."""
    score = report["score"]
    first_pass = score["citation_first_pass"]
    tasks = report["operator_tasks"]
    claims = report["diagnosis"]["claim_counts"] or {}
    return {
        "incident_id": run.incident_id,
        "split": run.split,
        "configuration": run.configuration,
        "repeat": run.repeat,
        **provenance,
        "status": report["status"],
        "partial": report["partial"],
        "cap_usd": report["cap_usd"],
        "spent_usd": report["spent_usd"],
        "predicted_usd": report["predicted_usd"],
        "under_cap": report["under_cap"],
        "wall_clock_s": report["wall_clock_s"],
        "by_model": {
            model: {
                k: v
                for k, v in row.items()
                if k in ("calls", "input_tokens", "output_tokens", "usd_real")
            }
            for model, row in report["by_model"].items()
        },
        "calls": report["calls"],
        "retries": report["retries"],
        "ledger_refusals": len(report["ledger_refusals"]),
        "operator_tasks": tasks,
        "unread_slices": len(report["unread_slices"]),
        "coverage": report.get("coverage"),
        "trimmed_citations": report["trimmed_citations"]["total"],
        "salvaged_replies": report["salvaged_replies"]["replies"],
        "top_up_usd": format_usd(
            sum((Decimal(m.get("top_up_usd", "0")) for m in report["managers"]), ZERO_USD)
        ),
        "diagnosis_status": report["diagnosis"]["status"],
        "diagnosis_category": report["diagnosis"]["category"],
        "diagnosis_repairs": report["diagnosis"]["repairs"],
        "claim_counts": {k: v for k, v in claims.items() if isinstance(v, int)},
        "score": {
            "diagnosis_correct": score["diagnosis_correct"],
            "category_correct": score["category_correct"],
            "evidence_recall": score["evidence_recall"],
            "citation_verified_rate": score["citation_verified_rate"],
            "citation_first_pass_validity": first_pass["validity"],
            "coverage": score.get("coverage"),
            "citation_repairs": score["citation_repairs"],
            "withdrawn_claims": score["withdrawn_claims"],
        },
    }


def provenance(root: Path = REPO_ROOT) -> dict[str, Any]:
    """The commit a run used, whether tracked files had changes, and a hash of the config
    files, so test results can be tied to one frozen state."""

    def git(*args: str) -> str:
        try:
            done = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, check=True
            )
        except (OSError, subprocess.CalledProcessError):
            return ""
        return done.stdout.strip()

    digest = hashlib.sha256()
    for name in CONFIG_FILES:
        path = root / name
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.exists() else b"")
    return {
        "commit": git("rev-parse", "HEAD") or None,
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "config_sha256": digest.hexdigest(),
    }


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# -- the summary -------------------------------------------------------------------------

SUMMARY_COLUMNS = (
    "split",
    "configuration",
    "runs",
    "incidents",
    "diagnosis_correct_rate",
    "category_correct_rate",
    "evidence_recall_mean",
    "citation_verified_rate_mean",
    "citation_first_pass_validity_mean",
    "coverage_mean",
    "spent_usd_mean",
    "spent_usd_total",
    "wall_clock_s_mean",
    "partial_runs",
    "operator_tasks_ok",
    "operator_tasks_total",
    "retried_attempts",
    "trimmed_citations",
    "commits",
)


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarize(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """One row per configuration, for each split apart."""
    rows: dict[str, list[dict[str, Any]]] = {split: [] for split in SPLITS}
    for split in SPLITS:
        in_split = [r for r in results if r["split"] == split]
        for configuration in sorted({r["configuration"] for r in in_split}):
            group = [r for r in in_split if r["configuration"] == configuration]
            spent = [Decimal(r["spent_usd"]) for r in group]
            scores = [r["score"] for r in group]
            rows[split].append(
                {
                    "split": split,
                    "configuration": configuration,
                    "runs": len(group),
                    "incidents": len({r["incident_id"] for r in group}),
                    "diagnosis_correct_rate": _mean(
                        [float(s["diagnosis_correct"]) for s in scores]
                    ),
                    "category_correct_rate": _mean([float(s["category_correct"]) for s in scores]),
                    "evidence_recall_mean": _mean([s["evidence_recall"] for s in scores]),
                    "citation_verified_rate_mean": _mean(
                        [s["citation_verified_rate"] for s in scores]
                    ),
                    "citation_first_pass_validity_mean": _mean(
                        [s["citation_first_pass_validity"] for s in scores]
                    ),
                    "coverage_mean": _mean([s.get("coverage") for s in scores]),
                    "spent_usd_mean": format_usd(sum(spent, ZERO_USD) / len(spent)),
                    "spent_usd_total": format_usd(sum(spent, ZERO_USD)),
                    "wall_clock_s_mean": _mean([r["wall_clock_s"] for r in group]),
                    "partial_runs": sum(bool(r["partial"]) for r in group),
                    "operator_tasks_ok": sum(r["operator_tasks"]["ok"] for r in group),
                    "operator_tasks_total": sum(r["operator_tasks"]["total"] for r in group),
                    "retried_attempts": sum(r["retries"]["retried_attempts"] for r in group),
                    "trimmed_citations": sum(r["trimmed_citations"] for r in group),
                    "commits": " ".join(sorted({(r["commit"] or "unknown")[:7] for r in group})),
                }
            )
    return rows


def _csv(rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=SUMMARY_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _markdown(rows: dict[str, list[dict[str, Any]]], results: list[dict[str, Any]]) -> str:
    shown = (
        "configuration",
        "runs",
        "incidents",
        "diagnosis_correct_rate",
        "category_correct_rate",
        "evidence_recall_mean",
        "citation_verified_rate_mean",
        "spent_usd_mean",
        "spent_usd_total",
        "partial_runs",
        "commits",
    )
    lines = [
        "# Benchmark results",
        "",
        "Written by scripts/run_benchmark.py from the result files in runs/ (metrics only). "
        "The test split is reported apart from the dev split; tuning ends before test runs.",
    ]
    for split in SPLITS:
        lines += ["", f"## {split.capitalize()} split", ""]
        if not rows[split]:
            lines.append("No runs yet.")
            continue
        commits = {r["commit"] for r in results if r["split"] == split}
        if split == "test" and len(commits) > 1:
            lines += [
                "WARNING: these test results come from more than one commit, so they may "
                "not all come from one frozen state.",
                "",
            ]
        lines.append("| " + " | ".join(shown) + " |")
        lines.append("|" + "---|" * len(shown))
        for row in rows[split]:
            cells = ["" if row[k] is None else str(row[k]) for k in shown]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_summary(results_dir: Path) -> dict[str, list[dict[str, Any]]]:
    files = sorted((results_dir / "runs").glob("*.json"))
    results = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    rows = summarize(results)
    for split in SPLITS:
        write_atomic(results_dir / f"summary-{split}.csv", _csv(rows[split]))
    write_atomic(results_dir / "summary.md", _markdown(rows, results))
    return rows


# -- the benchmark -----------------------------------------------------------------------


async def benchmark(
    config: dict[str, Any],
    *,
    split: str,
    live: bool,
    approve_total_usd: Decimal | None,
    freeze_confirmed: bool,
    results_dir: Path,
    cassette_dir: Path,
    tmp_dir: Path,
    loader: Loader = default_loader,
    truth_loader: TruthLoader = load_ground_truth,
    runner: Runner = run_incident.run,
    transport: Any = None,
    say: Callable[[str], None] = print,
    repeats: int | None = None,
) -> int:
    """Estimate, then (with `live`) run what is left of the plan. Returns an exit code:
    0 done, 2 refused before any run, 3 stopped part way (budget or an error)."""
    runs = planned_runs(config, split, truth_loader, repeats)
    todo = [run for run in runs if not result_path(results_dir, run).exists()]
    say(
        f"Planned runs: {len(runs)} ({split} split); done: {len(runs) - len(todo)}; "
        f"to run: {len(todo)}."
    )
    costs = await estimate(todo, config, loader, runner, tmp_dir)
    predicted = {run.name: costs[(run.incident_id, run.configuration)] for run in todo}
    total = sum(predicted.values(), ZERO_USD)
    worst = sum((run.cap_usd for run in todo), ZERO_USD)
    for (incident_id, configuration), usd in sorted(costs.items()):
        repeats = sum(
            r.incident_id == incident_id and r.configuration == configuration for r in todo
        )
        say(f"  {incident_id} {configuration}: USD {format_usd(usd)} per run x {repeats}")
    say(
        f"Predicted total (estimate mode): USD {format_usd(total)}; worst case (the sum of "
        f"the run caps): USD {format_usd(worst)}."
    )
    if not live:
        say("Estimate only: nothing was run. Pass --live --approve-total-usd to run.")
        return 0
    test_runs = sorted({run.incident_id for run in todo if run.split == "test"})
    if test_runs and not freeze_confirmed:
        say(
            f"Refused: {', '.join(test_runs)} are test-split incidents. Tuning must end "
            "before test runs: pass --freeze-confirmed once it has; nothing was run."
        )
        return 2
    if approve_total_usd is None or approve_total_usd < total:
        say(
            f"Refused: live runs need --approve-total-usd of at least USD {format_usd(total)}"
            "; nothing was run."
        )
        return 2
    if not todo:
        write_summary(results_dir)
        return 0
    spent = ZERO_USD
    origin = provenance()
    for run in todo:
        if spent + predicted[run.name] > approve_total_usd:
            say(
                f"Stopped before {run.name}: USD {format_usd(spent)} spent, and its predicted "
                f"USD {format_usd(predicted[run.name])} would pass the approved USD "
                f"{format_usd(approve_total_usd)}."
            )
            write_summary(results_dir)
            return 3
        bundle, truth = loader(run.incident_id)
        say(f"Running {run.name} (cap USD {format_usd(run.cap_usd)}).")
        try:
            report, _, _ = await runner(
                "record",
                run.incident_id,
                bundle=bundle,
                truth=truth,
                run_usd=str(run.cap_usd),
                cassette=cassette_dir / f"{run.name}.json",
                config=config,
                configuration=run.configuration,
                transport=transport,
            )
        except Exception as error:  # nothing is written for it, so it runs again next time
            say(f"Stopped: {run.name} raised {type(error).__name__}: {error}")
            write_summary(results_dir)
            return 3
        spent += Decimal(report["spent_usd"])
        if report.get("replay") == "partially replayed":
            say(
                f"Stopped: {run.name} was partially replayed from a reused cassette; a "
                "benchmark result must come from a full run. Nothing was written for it."
            )
            write_summary(results_dir)
            return 3
        result = metrics(report, run, {**origin, "finished_at": datetime.now(UTC).isoformat()})
        write_atomic(result_path(results_dir, run), json.dumps(result, indent=2) + "\n")
        say(
            f"  spent USD {report['spent_usd']}; diagnosis correct: "
            f"{result['score']['diagnosis_correct']}."
        )
    write_summary(results_dir)
    say(f"Done: USD {format_usd(spent)} spent by this invocation.")
    return 0


def _usd(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def main(argv: list[str] | None = None) -> int:
    config = run_incident.load_benchmark_config()
    plan = load_plan(config)
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--split", choices=(*SPLITS, "all"), default="dev")
    parser.add_argument(
        "--repeats",
        type=int,
        metavar="N",
        help=f"run repeats 1 to N only (at most the configured {plan['repeats']})",
    )
    parser.add_argument("--live", action="store_true", help="record runs (costs credits)")
    parser.add_argument("--approve-total-usd", help="live only: at least the predicted total")
    parser.add_argument(
        "--freeze-confirmed",
        action="store_true",
        help="tuning has ended: test-split incidents may run live",
    )
    parser.add_argument(
        "--reuse-cassette", help="refused: cassette reuse is for scripts/run_incident.py only"
    )
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.reuse_cassette is not None:
        print(
            "--reuse-cassette is refused: a benchmark run is never partially replayed; "
            "nothing was run."
        )
        return 2
    if args.repeats is not None and not 1 <= args.repeats <= int(plan["repeats"]):
        print(f"--repeats must be between 1 and the configured {plan['repeats']}; nothing was run.")
        return 2
    approved = _usd(args.approve_total_usd)
    if args.approve_total_usd is not None and approved is None:
        print("--approve-total-usd must be a positive amount; nothing was run.")
        return 2
    if args.live:
        if os.environ.get("HARNESS_MODE") != "record":
            print("Set HARNESS_MODE=record for live runs; nothing was run.")
            return 2
        load_dotenv(REPO_ROOT / ".env")
        if not os.environ.get("NEBIUS_API_KEY"):
            print("NEBIUS_API_KEY is not set in .env; nothing was run.")
            return 2
    tmp_dir = REPO_ROOT / "runs" / "benchmark-estimate"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(
        benchmark(
            config,
            split=args.split,
            repeats=args.repeats,
            live=args.live,
            approve_total_usd=approved,
            freeze_confirmed=args.freeze_confirmed,
            results_dir=REPO_ROOT / plan["results_dir"],
            cassette_dir=REPO_ROOT / plan["cassette_dir"],
            tmp_dir=tmp_dir,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
