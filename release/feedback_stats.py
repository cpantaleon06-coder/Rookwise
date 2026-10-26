"""Count API behaviour per model over the calls.json files of incident runs.

Reads runs/incidents/*/*/calls.json (written by scripts/run_incident.py) and prints a
markdown table, one row per model:

- calls: entries in calls.json; reused: those with `reused` true (a cassette hit, not sent);
- no attempt_log: calls without an `attempt_log` (runs written before it existed);
- attempts: `attempt_log` entries; retries: entries with `outcome` "retried";
- 422 / 429 / 529 / other 5xx / statuses seen: the `status_code` of every entry ("none"
  for an entry without one, such as a refused reservation or a timeout);
- finish length: calls with `finish_reason` "length";
- repair calls: calls whose `task_id` ends in "-repair".

Field names are the ones in the files. A field that is missing is reported in the notes
and its column is not filled from anything else. calls.json has no repair count field, so
re-prompts inside one call are not counted. Byte-identical calls.json files (copies of a
run folder) are read once.

The table mixes live and offline runs unless `--runs` selects folders: estimate and
reuse-check runs use a stub transport, so their statuses are synthetic.

Usage:
    python release/feedback_stats.py
    python release/feedback_stats.py --runs "record*" --skip-reused
    python release/feedback_stats.py --runs-dir PATH
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RAISED_STATUS = re.compile(r"HTTP (\d{3})")
COLUMNS = (
    "model",
    "calls",
    "reused",
    "no attempt_log",
    "attempts",
    "retries",
    "422",
    "429",
    "529",
    "other 5xx",
    "statuses seen",
    "finish length",
    "repair calls",
)


@dataclass
class ModelStats:
    calls: int = 0
    reused: int = 0
    without_attempt_log: int = 0
    attempts: int = 0
    retries: int = 0
    statuses: Counter[int | None] = field(default_factory=Counter)
    length: int = 0
    repair_calls: int = 0
    raised_statuses: Counter[int] = field(default_factory=Counter)

    def add(self, other: ModelStats) -> None:
        for name in (
            "calls",
            "reused",
            "without_attempt_log",
            "attempts",
            "retries",
            "length",
            "repair_calls",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.statuses.update(other.statuses)
        self.raised_statuses.update(other.raised_statuses)


@dataclass
class Stats:
    files: list[Path] = field(default_factory=list)
    copies: list[tuple[Path, Path]] = field(default_factory=list)
    by_model: dict[str, ModelStats] = field(default_factory=dict)
    calls_seen: int = 0
    # Calls with neither `finish_reason` nor `raised` (a call that raised has no finish).
    no_finish_no_raise: int = 0
    skipped_reused: int = 0
    call_fields: Counter[str] = field(default_factory=Counter)
    attempt_fields: Counter[str] = field(default_factory=Counter)
    attempts_seen: int = 0


def find_call_files(runs_dir: Path, runs: str = "*") -> list[Path]:
    return sorted((runs_dir / "incidents").glob(f"*/{runs}/calls.json"))


def collect(files: list[Path], skip_reused: bool = False) -> Stats:
    stats = Stats()
    first: dict[str, Path] = {}
    for path in files:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in first:
            stats.copies.append((path, first[digest]))
            continue
        first[digest] = path
        stats.files.append(path)
        calls = json.loads(data)
        if not isinstance(calls, list):
            raise ValueError(f"{path}: expected a list of calls")
        for call in calls:
            add_call(stats, call, skip_reused)
    return stats


def add_call(stats: Stats, call: dict[str, Any], skip_reused: bool) -> None:
    stats.calls_seen += 1
    stats.call_fields.update(call.keys())
    stats.no_finish_no_raise += "finish_reason" not in call and "raised" not in call
    if skip_reused and call.get("reused") is True:
        stats.skipped_reused += 1
        return
    row = stats.by_model.setdefault(str(call.get("model", "(no model)")), ModelStats())
    row.calls += 1
    row.reused += call.get("reused") is True
    row.length += call.get("finish_reason") == "length"
    row.repair_calls += str(call.get("task_id") or "").endswith("-repair")
    log = call.get("attempt_log")
    if log is None:
        row.without_attempt_log += 1
        raised = RAISED_STATUS.search(str(call.get("raised", "")))
        if raised:
            row.raised_statuses[int(raised.group(1))] += 1
        return
    for entry in log:
        stats.attempts_seen += 1
        stats.attempt_fields.update(entry.keys())
        row.attempts += 1
        row.retries += entry.get("outcome") == "retried"
        row.statuses[entry.get("status_code")] += 1


def status_list(statuses: Counter[int | None]) -> str:
    known = sorted((s, n) for s, n in statuses.items() if s is not None)
    parts = [f"{s}: {n}" for s, n in known]
    if statuses.get(None):
        parts.append(f"none: {statuses[None]}")
    return ", ".join(parts) or "-"


def row_cells(model: str, row: ModelStats) -> list[str]:
    other_5xx = sum(n for s, n in row.statuses.items() if s and 500 <= s < 600 and s != 529)
    return [
        model,
        str(row.calls),
        str(row.reused),
        str(row.without_attempt_log),
        str(row.attempts),
        str(row.retries),
        str(row.statuses.get(422, 0)),
        str(row.statuses.get(429, 0)),
        str(row.statuses.get(529, 0)),
        str(other_5xx),
        status_list(row.statuses),
        str(row.length),
        str(row.repair_calls),
    ]


def notes(stats: Stats, base: Path) -> list[str]:
    out: list[str] = []
    calls = stats.calls_seen
    for name in ("model", "attempt_log", "task_id"):
        have = stats.call_fields.get(name, 0)
        if have < calls:
            out.append(f"`{name}` is missing in {calls - have} of {calls} calls.")
    if stats.no_finish_no_raise:
        out.append(
            f"`finish_reason` is missing in {stats.no_finish_no_raise} of {calls} calls "
            "that did not raise."
        )
    for name in ("status_code", "outcome"):
        have = stats.attempt_fields.get(name, 0)
        if have < stats.attempts_seen:
            out.append(
                f"`{name}` is missing in {stats.attempts_seen - have} of "
                f"{stats.attempts_seen} attempt_log entries."
            )
    repair_fields = sorted(
        {k for k in stats.call_fields if "repair" in k}
        | {k for k in stats.attempt_fields if "repair" in k}
    )
    if repair_fields:
        out.append(f"Repair fields found but not counted: {', '.join(repair_fields)}.")
    else:
        out.append(
            "No repair field exists in calls.json (calls or attempt_log entries). "
            '`repair calls` counts separate calls whose task_id ends in "-repair"; '
            "re-prompts inside one call are not recorded there."
        )
    if any(r.without_attempt_log for r in stats.by_model.values()):
        out.append("Calls without attempt_log have no attempts, retries or statuses counted.")
    raised = [
        f"{model} HTTP {status} x{n}"
        for model, row in sorted(stats.by_model.items())
        for status, n in sorted(row.raised_statuses.items())
    ]
    if raised:
        out.append(
            "The `raised` text of calls without attempt_log names: "
            + ", ".join(raised)
            + " (not in the status columns)."
        )
    if stats.skipped_reused:
        out.append(f"{stats.skipped_reused} reused calls skipped (--skip-reused).")
    for copy, original in stats.copies:
        out.append(f"Skipped {rel(copy, base)}: same bytes as {rel(original, base)}.")
    return out


def rel(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def render(stats: Stats, base: Path) -> str:
    lines = [
        "# Feedback stats",
        "",
        f"{len(stats.files)} calls.json files read, {len(stats.copies)} identical copies "
        f"skipped, {stats.calls_seen} calls.",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "|".join("---" for _ in COLUMNS) + "|",
    ]
    total = ModelStats()
    for model, row in sorted(stats.by_model.items()):
        lines.append("| " + " | ".join(row_cells(model, row)) + " |")
        total.add(row)
    if stats.by_model:
        lines.append("| " + " | ".join(row_cells("**total**", total)) + " |")
    lines += ["", "Notes:", ""]
    lines += [f"- {note}" for note in notes(stats, base)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    parser.add_argument("--runs", default="*", help="run folder glob, for example 'record*'")
    parser.add_argument("--skip-reused", action="store_true", help="leave out cassette hits")
    args = parser.parse_args(argv)
    files = find_call_files(args.runs_dir, args.runs)
    if not files:
        print(f"no calls.json under {args.runs_dir / 'incidents'} matching {args.runs!r}")
        return 1
    stats = collect(files, skip_reused=args.skip_reused)
    sys.stdout.write(render(stats, args.runs_dir.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
