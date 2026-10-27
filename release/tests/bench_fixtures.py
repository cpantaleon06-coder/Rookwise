"""Small synthetic benchmark result folders for the release tests (not real runs)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

COMMITS = {
    "dev": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "test": "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
}
INCIDENTS = {"dev": ("inc-01", "inc-03", "inc-05"), "test": ("inc-02", "inc-04", "inc-06")}
# Per configuration: per-incident (diagnosis_correct, evidence_recall, coverage, spent, wall).
VALUES = {
    "a": [(True, 1.0, 0.9, "0.300000", 100.0), (True, 0.5, 0.8, "0.200000", 200.0),
          (False, 0.0, 1.0, "0.100000", 300.0)],
    "b": [(False, 0.0, 0.1, "0.400000", 10.0), (False, 0.5, 0.2, "0.400000", 20.0),
          (False, 0.25, 0.3, "0.400001", 30.0)],
    "c": [(True, 0.5, 0.7, "0.120000", 50.0), (False, 0.0, 0.7, "0.110000", 60.0),
          (False, 0.0, 0.7, "0.130000", 70.0)],
}  # fmt: skip
CSV_COLUMNS = (
    "split", "configuration", "runs", "incidents", "diagnosis_correct_rate",
    "evidence_recall_mean", "coverage_mean", "spent_usd_mean", "spent_usd_total",
    "wall_clock_s_mean", "commits",
)  # fmt: skip


def run_record(split: str, configuration: str, index: int, **overrides) -> dict:
    correct, recall, coverage, spent, wall = VALUES[configuration][index]
    record = {
        "incident_id": INCIDENTS[split][index],
        "split": split,
        "configuration": configuration,
        "repeat": 1,
        "commit": COMMITS[split],
        "dirty": False,
        "status": "finished",
        "partial": True,
        "cap_usd": "0.500000",
        "spent_usd": spent,
        "wall_clock_s": wall,
        "coverage": {"slices_read": 7, "slices_total": 10, "fraction": coverage},
        "diagnosis_status": "audited",
        "diagnosis_category": "bad_config",
        "score": {
            "diagnosis_correct": correct,
            "category_correct": correct,
            "evidence_recall": recall,
            "citation_verified_rate": 1.0,
            "citation_first_pass_validity": 0.9,
            "coverage": coverage,
        },
    }
    record.update(overrides)
    return record


def summary_row(split: str, configuration: str) -> dict[str, str]:
    """The summary row as scripts/run_benchmark.py would write it, computed by hand here."""
    values = VALUES[configuration]
    n = len(values)
    total = sum(float(v[3]) for v in values)
    return {
        "split": split,
        "configuration": configuration,
        "runs": str(n),
        "incidents": str(n),
        "diagnosis_correct_rate": str(round(sum(v[0] for v in values) / n, 4)),
        "evidence_recall_mean": str(round(sum(v[1] for v in values) / n, 4)),
        "coverage_mean": str(round(sum(v[2] for v in values) / n, 4)),
        "spent_usd_mean": f"{total / n:.6f}",
        "spent_usd_total": f"{total:.6f}",
        "wall_clock_s_mean": str(round(sum(v[4] for v in values) / n, 4)),
        "commits": COMMITS[split][:7],
    }


def write_results(root: Path, rows_override: dict | None = None) -> Path:
    """18 run files (dev/test x a/b/c x 3) plus matching summary CSVs under root."""
    runs = root / "runs"
    runs.mkdir(parents=True)
    for split in ("dev", "test"):
        for configuration in ("a", "b", "c"):
            for index in range(3):
                record = run_record(split, configuration, index)
                name = f"{record['incident_id']}__{configuration}__r1.json"
                (runs / name).write_text(json.dumps(record), encoding="utf-8")
        write_summary(root, split, rows_override)
    return root


def write_summary(root: Path, split: str, rows_override: dict | None = None) -> None:
    rows = [summary_row(split, c) for c in ("a", "b", "c")]
    for row in rows:
        row.update((rows_override or {}).get((split, row["configuration"]), {}))
    with (root / f"summary-{split}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def edit_run(root: Path, name: str, **changes) -> None:
    path = root / "runs" / name
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(changes)
    path.write_text(json.dumps(record), encoding="utf-8")
