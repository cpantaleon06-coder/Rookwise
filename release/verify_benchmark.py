"""Recompute the benchmark aggregates from the run files and compare them with the summaries.

Reads benchmarks/results/runs/<incident>__<config>__r<repeat>.json and, per (split,
configuration), recomputes: the number of runs, the diagnosis_correct count, the mean
score.evidence_recall, the mean coverage.fraction, the total and mean spent_usd and the
total wall_clock_s. Prints them as a table, then one PASS or FAIL line per check:

- file count: exactly 18 run files;
- runs per group: exactly 3 runs for each of dev/test x a/b/c, and no other group;
- not dirty: no run file has `dirty` true;
- under cap: spent_usd <= cap_usd in every run file (compared as decimals);
- summary-dev.csv and summary-test.csv: every group has one row, every row has a group,
  and runs, diagnosis_correct_rate, evidence_recall_mean, coverage_mean (tolerance 1e-4),
  spent_usd_total, spent_usd_mean (tolerance 1e-6) and wall_clock_s_mean (tolerance 1e-4)
  match; the `commits` column matches the short commits of the group's run files;
- known-good values: the correct count and total spent (all groups) and the mean recall
  and mean coverage (test groups) match the values recorded in KNOWN_GOOD below.
  Skipped with --skip-known-good (for other result folders).

The distinct `commit` values are listed after the checks. The exit code is 1 on any FAIL.
Only reads files; no network, no model calls.

Usage:
    python release/verify_benchmark.py
    python release/verify_benchmark.py --results-dir PATH --skip-known-good
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "benchmarks" / "results"
SPLITS = ("dev", "test")
CONFIGURATIONS = ("a", "b", "c")
EXPECTED_FILES = 18
EXPECTED_RUNS_PER_GROUP = 3
RATE_TOLERANCE = 1e-4
USD_TOLERANCE = 1e-6

# (split, configuration): correct count, total spent (USD), mean recall, mean coverage.
# Recall and coverage were recorded for the test split only.
KNOWN_GOOD: dict[tuple[str, str], dict[str, float]] = {
    ("dev", "a"): {"correct": 3, "spent_usd_total": 0.868538},
    ("dev", "b"): {"correct": 1, "spent_usd_total": 1.227259},
    ("dev", "c"): {"correct": 1, "spent_usd_total": 0.362161},
    ("test", "a"): {
        "correct": 2,
        "spent_usd_total": 0.749984,
        "evidence_recall_mean": 0.3333,
        "coverage_mean": 0.9203,
    },
    ("test", "b"): {
        "correct": 0,
        "spent_usd_total": 1.156681,
        "evidence_recall_mean": 0.2222,
        "coverage_mean": 0.1074,
    },
    ("test", "c"): {
        "correct": 1,
        "spent_usd_total": 0.356007,
        "evidence_recall_mean": 0.2222,
        "coverage_mean": 0.705,
    },
}


@dataclass
class Run:
    name: str
    incident_id: str
    split: str
    configuration: str
    repeat: int
    commit: str
    dirty: bool
    cap_usd: Decimal
    spent_usd: Decimal
    wall_clock_s: float
    diagnosis_correct: bool
    category_correct: bool
    evidence_recall: float
    coverage: float
    raw: dict


@dataclass
class Aggregate:
    split: str
    configuration: str
    runs: int
    correct: int
    evidence_recall_mean: float
    coverage_mean: float
    spent_usd_total: Decimal
    spent_usd_mean: Decimal
    wall_clock_s_total: float
    commits: list[str]

    @property
    def correct_rate(self) -> float:
        return self.correct / self.runs if self.runs else 0.0

    @property
    def wall_clock_s_mean(self) -> float:
        return self.wall_clock_s_total / self.runs if self.runs else 0.0


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)


def usd(value: object) -> Decimal:
    """spent_usd and cap_usd are six-decimal strings in the files; numbers are accepted too."""
    return Decimal(str(value))


def load_runs(runs_dir: Path) -> list[Run]:
    runs = []
    for path in sorted(runs_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        score = data["score"]
        runs.append(
            Run(
                name=path.name,
                incident_id=data["incident_id"],
                split=data["split"],
                configuration=data["configuration"],
                repeat=int(data["repeat"]),
                commit=data["commit"],
                dirty=bool(data["dirty"]),
                cap_usd=usd(data["cap_usd"]),
                spent_usd=usd(data["spent_usd"]),
                wall_clock_s=float(data["wall_clock_s"]),
                diagnosis_correct=bool(score["diagnosis_correct"]),
                category_correct=bool(score["category_correct"]),
                evidence_recall=float(score["evidence_recall"]),
                coverage=float(data["coverage"]["fraction"]),
                raw=data,
            )
        )
    return runs


def group_key(split: str, configuration: str) -> tuple[int, int, str, str]:
    """Sort order: known splits and configurations first, in their declared order."""
    s = SPLITS.index(split) if split in SPLITS else len(SPLITS)
    c = CONFIGURATIONS.index(configuration) if configuration in CONFIGURATIONS else 99
    return (s, c, split, configuration)


def aggregate(runs: Iterable[Run]) -> list[Aggregate]:
    groups: dict[tuple[str, str], list[Run]] = {}
    for run in runs:
        groups.setdefault((run.split, run.configuration), []).append(run)
    out = []
    for (split, configuration), members in sorted(
        groups.items(), key=lambda item: group_key(*item[0])
    ):
        n = len(members)
        total = sum((r.spent_usd for r in members), Decimal(0))
        out.append(
            Aggregate(
                split=split,
                configuration=configuration,
                runs=n,
                correct=sum(r.diagnosis_correct for r in members),
                evidence_recall_mean=sum(r.evidence_recall for r in members) / n,
                coverage_mean=sum(r.coverage for r in members) / n,
                spent_usd_total=total,
                spent_usd_mean=total / n,
                wall_clock_s_total=sum(r.wall_clock_s for r in members),
                commits=sorted({r.commit for r in members}),
            )
        )
    return out


def format_table(aggregates: list[Aggregate]) -> str:
    header = (
        "split",
        "config",
        "runs",
        "correct",
        "recall mean",
        "coverage mean",
        "spent total",
        "spent mean",
        "wall total s",
    )
    rows = [
        (
            a.split,
            a.configuration,
            str(a.runs),
            str(a.correct),
            f"{a.evidence_recall_mean:.4f}",
            f"{a.coverage_mean:.4f}",
            f"{a.spent_usd_total:.6f}",
            f"{a.spent_usd_mean:.6f}",
            f"{a.wall_clock_s_total:.2f}",
        )
        for a in aggregates
    ]
    widths = [max(len(row[i]) for row in (header, *rows)) for i in range(len(header))]
    lines = [
        "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip()
        for row in (header, *rows)
    ]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def check_file_count(runs: list[Run], expected: int = EXPECTED_FILES) -> CheckResult:
    return CheckResult(
        f"exactly {expected} run files", len(runs) == expected, [f"found {len(runs)}"]
    )


def check_runs_per_group(
    aggregates: list[Aggregate], expected: int = EXPECTED_RUNS_PER_GROUP
) -> CheckResult:
    result = CheckResult(f"{expected} runs per (split, configuration)", True)
    found = {(a.split, a.configuration): a.runs for a in aggregates}
    for split in SPLITS:
        for configuration in CONFIGURATIONS:
            n = found.pop((split, configuration), 0)
            if n != expected:
                result.passed = False
                result.details.append(f"{split} {configuration}: {n} runs")
    for (split, configuration), n in found.items():
        result.passed = False
        result.details.append(f"unexpected group {split} {configuration}: {n} runs")
    return result


def check_not_dirty(runs: list[Run]) -> CheckResult:
    dirty = [r.name for r in runs if r.dirty]
    return CheckResult("no run file has dirty true", not dirty, dirty)


def check_under_cap(runs: list[Run]) -> CheckResult:
    over = [
        f"{r.name}: spent {r.spent_usd} > cap {r.cap_usd}" for r in runs if r.spent_usd > r.cap_usd
    ]
    return CheckResult("spent_usd <= cap_usd in every run file", not over, over)


def read_summary(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def close(a: float, b: float, tolerance: float) -> bool:
    # A small slack absorbs float error when the difference sits exactly on the tolerance.
    return abs(a - b) <= tolerance + 1e-12


def compare_summary(path: Path, split: str, aggregates: list[Aggregate]) -> CheckResult:
    result = CheckResult(f"{path.name} matches the run files", True)
    if not path.is_file():
        return CheckResult(result.name, False, [f"{path} not found"])
    ours = {a.configuration: a for a in aggregates if a.split == split}
    rows = read_summary(path)
    seen = set()
    for row in rows:
        configuration = row.get("configuration", "")
        label = f"{split} {configuration}"
        if row.get("split") != split:
            result.passed = False
            result.details.append(f"row for split {row.get('split')!r} in {path.name}")
            continue
        if configuration in seen:
            result.passed = False
            result.details.append(f"{label}: duplicate row")
            continue
        seen.add(configuration)
        agg = ours.get(configuration)
        if agg is None:
            result.passed = False
            result.details.append(f"{label}: row has no run files")
            continue
        comparisons = (
            ("runs", float(agg.runs), 0.0),
            ("diagnosis_correct_rate", agg.correct_rate, RATE_TOLERANCE),
            ("evidence_recall_mean", agg.evidence_recall_mean, RATE_TOLERANCE),
            ("coverage_mean", agg.coverage_mean, RATE_TOLERANCE),
            ("spent_usd_total", float(agg.spent_usd_total), USD_TOLERANCE),
            ("spent_usd_mean", float(agg.spent_usd_mean), USD_TOLERANCE),
            ("wall_clock_s_mean", agg.wall_clock_s_mean, RATE_TOLERANCE),
        )
        for column, value, tolerance in comparisons:
            try:
                theirs = float(row[column])
            except (KeyError, ValueError):
                result.passed = False
                result.details.append(f"{label}: column {column} missing or not a number")
                continue
            if not close(value, theirs, tolerance):
                result.passed = False
                result.details.append(
                    f"{label}: {column} csv {row[column]} vs recomputed {value:.6f}"
                )
        listed = sorted(c for c in row.get("commits", "").replace(";", " ").split() if c)
        mismatched = [c for c in agg.commits if not any(c.startswith(s) for s in listed)]
        if not listed or mismatched:
            result.passed = False
            result.details.append(
                f"{label}: commits csv {row.get('commits')!r} vs files "
                f"{', '.join(c[:7] for c in agg.commits)}"
            )
    for configuration in sorted(set(ours) - seen):
        result.passed = False
        result.details.append(f"{split} {configuration}: no row in {path.name}")
    return result


def check_known_good(
    aggregates: list[Aggregate], known: dict[tuple[str, str], dict[str, float]] = KNOWN_GOOD
) -> CheckResult:
    result = CheckResult("matches the known-good values", True)
    ours = {(a.split, a.configuration): a for a in aggregates}
    for key, values in known.items():
        label = " ".join(key)
        agg = ours.get(key)
        if agg is None:
            result.passed = False
            result.details.append(f"{label}: no run files")
            continue
        recomputed = {
            "correct": float(agg.correct),
            "spent_usd_total": float(agg.spent_usd_total),
            "evidence_recall_mean": agg.evidence_recall_mean,
            "coverage_mean": agg.coverage_mean,
        }
        for name, expected in values.items():
            if name in ("evidence_recall_mean", "coverage_mean"):
                ok = close(recomputed[name], expected, RATE_TOLERANCE)
            elif name == "spent_usd_total":
                ok = close(recomputed[name], expected, USD_TOLERANCE)
            else:
                ok = recomputed[name] == expected
            if not ok:
                result.passed = False
                result.details.append(
                    f"{label}: {name} expected {expected} recomputed {recomputed[name]:.6f}"
                )
    return result


def run_checks(
    results_dir: Path, runs: list[Run], aggregates: list[Aggregate], known_good: bool = True
) -> list[CheckResult]:
    results = [
        check_file_count(runs),
        check_runs_per_group(aggregates),
        check_not_dirty(runs),
        check_under_cap(runs),
        compare_summary(results_dir / "summary-dev.csv", "dev", aggregates),
        compare_summary(results_dir / "summary-test.csv", "test", aggregates),
    ]
    if known_good:
        results.append(check_known_good(aggregates))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help="folder with runs/, summary-dev.csv and summary-test.csv",
    )
    parser.add_argument(
        "--skip-known-good", action="store_true", help="do not compare with KNOWN_GOOD"
    )
    args = parser.parse_args(argv)
    results_dir = args.results_dir.resolve()
    runs = load_runs(results_dir / "runs")
    aggregates = aggregate(runs)
    print(format_table(aggregates))
    print()
    results = run_checks(results_dir, runs, aggregates, known_good=not args.skip_known_good)
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'}  {result.name}")
        for detail in result.details:
            print(f"      {detail}")
    print()
    commits = sorted({r.commit for r in runs})
    print(f"distinct commits ({len(commits)}):")
    for commit in commits:
        groups = sorted({f"{r.split} {r.configuration}" for r in runs if r.commit == commit})
        print(f"  {commit}  ({', '.join(groups)})")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
