"""Classify the citations of a team_smoke run that failed with quote_not_found. Offline.

Reads a report.json written by scripts/team_smoke.py (its `citations` list) and the
scenario's source files, and puts every failed citation in one class, checked in order:

- line_offset: the quote, after the evidence check's whitespace normalization, is in the
  same source on other lines. Reported: the true first and last line of the occurrence
  nearest the cited line_start, and the distance (true first line minus cited line_start).
- altered: no exact occurrence, but a near one: the best similarity ratio (difflib) of the
  quote against any window of consecutive lines is at least the threshold (0.8 by
  default). Reported: that ratio and the window's first line.
- absent: no near match anywhere in the source (the best ratio is still reported).

The ratio compares the quote with the best-aligned stretch of a window of the same length
(a partial ratio), so a short quote taken from a long line is not penalized for the rest
of the line. Windows run from 1 line to the cited range's width plus 2 (at most 20); a tie
goes to the smaller window, then to the lower line.
Counts are printed per class, per model and per range width (1 line, 2 to 4, 5 or more).

Usage:
    python scripts/classify_citation_failures.py
    python scripts/classify_citation_failures.py --report runs/team_smoke/record/report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))  # noqa: E402 (lets `rookwise` resolve from a checkout)

from rookwise.evidence import normalize_whitespace, split_lines  # noqa: E402

DEFAULT_REPORT = REPO_ROOT / "runs" / "team_smoke" / "record" / "report.json"
DEFAULT_SCENARIO = REPO_ROOT / "examples" / "team_smoke"
THRESHOLD = 0.8
MAX_WINDOW = 20
CLASSES = ("line_offset", "altered", "absent")
WIDTHS = ("1 line", "2 to 4", "5 or more")


def width_bucket(line_start: int, line_end: int) -> str:
    width = line_end - line_start + 1
    if width <= 1:
        return "1 line"
    return "2 to 4" if width <= 4 else "5 or more"


def _joined(lines: list[str]) -> tuple[str, list[tuple[int, int, int]]]:
    """The source as the evidence check reads it (lines joined by one space, whitespace
    normalized) and the character span of every non-empty line: (first, end, line)."""
    parts: list[str] = []
    spans: list[tuple[int, int, int]] = []
    position = 0
    for number, line in enumerate(lines, 1):
        text = normalize_whitespace(line)
        if not text:
            continue
        if parts:
            position += 1
        spans.append((position, position + len(text), number))
        parts.append(text)
        position += len(text)
    return " ".join(parts), spans


def exact_occurrences(lines: list[str], quote: str) -> list[tuple[int, int]]:
    """(first line, last line) of every occurrence of the normalized quote in the source."""
    joined, spans = _joined(lines)
    quote = normalize_whitespace(quote)
    found = []
    start = joined.find(quote) if quote else -1
    while start != -1:
        end = start + len(quote)
        numbers = [n for first, last, n in spans if first < end and start < last]
        found.append((numbers[0], numbers[-1]))
        start = joined.find(quote, start + 1)
    return found


def partial_ratio(quote: str, text: str) -> float:
    """The best ratio of `quote` against a stretch of `text` of the same length."""
    if not quote or not text:
        return 0.0
    if len(text) <= len(quote):
        return SequenceMatcher(None, quote, text, autojunk=False).ratio()
    best = 0.0
    blocks = SequenceMatcher(None, text, quote, autojunk=False).get_matching_blocks()
    for block in blocks:
        start = min(max(block.a - block.b, 0), len(text) - len(quote))
        piece = text[start : start + len(quote)]
        best = max(best, SequenceMatcher(None, quote, piece, autojunk=False).ratio())
    return best


def best_window(lines: list[str], quote: str, max_window: int) -> tuple[float, int]:
    """The best partial ratio over windows of 1 to `max_window` lines, and the window's
    first line. Ties go to the smaller window, then to the lower line."""
    quote = normalize_whitespace(quote)
    best, line = 0.0, 0
    for size in range(1, max_window + 1):
        for first in range(len(lines) - size + 1):
            text = normalize_whitespace(" ".join(lines[first : first + size]))
            ratio = partial_ratio(quote, text)
            if ratio > best:
                best, line = ratio, first + 1
    return best, line


def classify(citation: dict[str, Any], text: str, threshold: float = THRESHOLD) -> dict[str, Any]:
    lines = split_lines(text)
    start, end = citation["line_start"], citation["line_end"]
    row: dict[str, Any] = {
        "claim_id": citation.get("claim_id"),
        "model": citation.get("model"),
        "source_id": citation["source_id"],
        "line_start": start,
        "line_end": end,
        "width": width_bucket(start, end),
        "quote": citation["quote"],
    }
    found = exact_occurrences(lines, citation["quote"])
    if found:
        first, last = min(found, key=lambda span: (abs(span[0] - start), span[0]))
        return row | {
            "class": "line_offset",
            "true_line_start": first,
            "true_line_end": last,
            "distance": first - start,
        }
    window = min(max(end - start + 1, 1) + 2, MAX_WINDOW)
    ratio, nearest = best_window(lines, citation["quote"], window)
    return row | {
        "class": "altered" if ratio >= threshold else "absent",
        "ratio": round(ratio, 3),
        "nearest_line": nearest,
    }


def classify_report(
    report: dict[str, Any], sources: dict[str, str], threshold: float = THRESHOLD
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """The classified quote_not_found citations, and how many failed citations had
    another reason (left out)."""
    rows, other = [], Counter()
    for citation in report.get("citations", []):
        if citation.get("status") != "failed":
            continue
        if citation.get("reason") != "quote_not_found" or citation["source_id"] not in sources:
            other[citation.get("reason") or "unknown"] += 1
            continue
        rows.append(classify(citation, sources[citation["source_id"]], threshold))
    return rows, other


def load_sources(scenario_dir: Path) -> dict[str, str]:
    scenario = json.loads((scenario_dir / "scenario.json").read_text("utf-8"))
    return {
        source_id: (scenario_dir / name).read_text("utf-8")
        for source_id, name in scenario["sources"].items()
    }


def _table(title: str, header: list[str], body: list[list[Any]]) -> str:
    lines = [f"### {title}", "", "| " + " | ".join(header) + " |"]
    lines.append("|" + "---|" * len(header))
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in body]
    return "\n".join(lines)


def render(rows: list[dict[str, Any]], other: Counter[str]) -> str:
    classes = Counter(r["class"] for r in rows)
    parts = [
        _table(
            "Per class",
            ["Class", "Citations"],
            [[c, classes[c]] for c in CLASSES] + [["All", len(rows)]],
        )
    ]
    models = sorted({str(r["model"]) for r in rows})
    parts.append(
        _table(
            "Per model",
            ["Model", *CLASSES, "All"],
            [
                [m, *(sum(str(r["model"]) == m and r["class"] == c for r in rows) for c in CLASSES)]
                + [sum(str(r["model"]) == m for r in rows)]
                for m in models
            ],
        )
    )
    parts.append(
        _table(
            "Per range width",
            ["Cited lines", *CLASSES, "All"],
            [
                [w, *(sum(r["width"] == w and r["class"] == c for r in rows) for c in CLASSES)]
                + [sum(r["width"] == w for r in rows)]
                for w in WIDTHS
            ],
        )
    )
    detail = []
    for r in rows:
        if r["class"] == "line_offset":
            found = f"true lines {r['true_line_start']}-{r['true_line_end']}, "
            found += f"distance {r['distance']:+d}"
        else:
            found = f"ratio {r['ratio']}, nearest line {r['nearest_line']}"
        quote = json.dumps(r["quote"], ensure_ascii=False).replace("|", "\\|")
        detail.append(
            [
                r["claim_id"],
                r["model"],
                r["source_id"],
                f"{r['line_start']}-{r['line_end']}",
                r["class"],
                found,
                quote,
            ]
        )
    parts.append(
        _table(
            "Each citation",
            ["Claim", "Model", "Source", "Cited", "Class", "Found", "Quote"],
            detail,
        )
    )
    if other:
        listed = ", ".join(f"{reason} {count}" for reason, count in sorted(other.items()))
        parts.append(f"Failed for another reason (not classified): {listed}.")
    return "\n\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not args.report.exists():
        print(f"No report at {args.report}.")
        return 2
    report = json.loads(args.report.read_text("utf-8"))
    if "citations" not in report:
        print("The report has no `citations` list (written before citation detail was kept).")
        return 2
    rows, other = classify_report(report, load_sources(args.scenario_dir), args.threshold)
    print(render(rows, other), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
