"""Report whether the test-split numbers in results.json appear in README.md and the landing page.

For each test-split aggregate in release/out/results.json (written by results_json.py),
in the order (a), (b), (c), the expected strings are:

- the correct count as "<n> of <runs>" (for example "2 of 3");
- the mean coverage rounded half up to 3 decimals (for example "0.920");
- the mean cost per run rounded half up to 3 decimals (for example "0.250").

Each string is searched as plain text in README.md and web/src/pages/Landing.tsx. A JSX
source that renders the count and "of 3" from separate expressions does not contain the
literal text, so it is reported as missing there. Both files are only read, never changed.

Prints a table (value, what, then found or missing per file) and the missing ones. The
exit code is 1 when any expected string is missing from any file.

Usage:
    python release/check_numbers.py
    python release/check_numbers.py --results PATH --root PATH
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from results_json import CONFIG_ORDER, LABELS, OUT_PATH, three

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("README.md", "web/src/pages/Landing.tsx")


@dataclass
class Expected:
    value: str
    what: str


def expected_strings(results: dict, split: str = "test") -> list[Expected]:
    rows = [a for a in results["aggregates"] if a["split"] == split]
    rows.sort(
        key=lambda a: (
            CONFIG_ORDER.index(a["configuration"]) if a["configuration"] in CONFIG_ORDER else 99
        )
    )
    out: list[Expected] = []
    for kind in ("correct", "coverage", "cost"):
        for a in rows:
            label = LABELS.get(a["configuration"], a["configuration"])
            if kind == "correct":
                out.append(Expected(f"{a['diagnosis_correct']} of {a['runs']}", f"{label} correct"))
            elif kind == "coverage":
                out.append(Expected(three(a["coverage_mean"]), f"{label} mean coverage"))
            else:
                out.append(Expected(three(a["spent_usd_mean"]), f"{label} mean cost (USD)"))
    return out


def read_targets(root: Path, targets: tuple[str, ...] = TARGETS) -> dict[str, str | None]:
    texts: dict[str, str | None] = {}
    for name in targets:
        path = root / name
        texts[name] = path.read_text(encoding="utf-8") if path.is_file() else None
    return texts


def find(expected: list[Expected], texts: dict[str, str | None]) -> dict[str, dict[str, bool]]:
    """{value: {file: found}}; a file that does not exist counts as not found."""
    return {
        e.value: {name: text is not None and e.value in text for name, text in texts.items()}
        for e in expected
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=OUT_PATH, help="results.json to read")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    args = parser.parse_args(argv)
    if not args.results.is_file():
        print(f"{args.results} not found; run release/results_json.py first", file=sys.stderr)
        return 1
    results = json.loads(args.results.read_text(encoding="utf-8"))
    expected = expected_strings(results)
    texts = read_targets(args.root.resolve())
    for name, text in texts.items():
        if text is None:
            print(f"note: {name} not found")
    found = find(expected, texts)

    header = ["value", "what", *texts]
    rows = [
        [e.value, e.what, *("found" if found[e.value][n] else "MISSING" for n in texts)]
        for e in expected
    ]
    widths = [max(len(r[i]) for r in (header, *rows)) for i in range(len(header))]
    for row in (header, ["-" * w for w in widths], *rows):
        print("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip())

    missing = [(e, n) for e in expected for n in texts if not found[e.value][n]]
    print()
    if not missing:
        print("all test-split numbers found in every file")
        return 0
    print(f"missing ({len(missing)}):")
    for e, name in missing:
        print(f"  {name}: {e.value!r} ({e.what})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
