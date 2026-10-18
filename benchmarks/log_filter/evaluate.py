"""Score the stage-0 log filters on the SYNTHETIC corpus (see PROTOCOL.md).

Reads corpus/<id>/truth.json, the generated logs and the Laya chunk scores in
results/laya/<id>.json (written by tools/laya-filter/score.mjs). Picks the Laya thresholds on
the dev incidents only, applies them once to the test incidents, and writes results/summary.json
plus the tables printed to stdout.

    python benchmarks/log_filter/evaluate.py             # needs scores for all six incidents
    python benchmarks/log_filter/evaluate.py --dev-only  # dev numbers and thresholds only

No network, no model calls.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from filter_keyword import kept_lines as keyword_kept  # noqa: E402

from rookwise.evidence import split_lines  # noqa: E402  (same 1-based numbering as the auditor)

CORPUS = HERE / "corpus"
LAYA = HERE / "results" / "laya"
DEV = ["dev-1", "dev-2", "dev-3"]
TEST = ["test-1", "test-2", "test-3"]
FORMS = {"C": "p_C", "C2": "p_C2"}
GRID = [0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99]


def chars_per_token() -> int:
    cfg = json.loads((ROOT / "config" / "harness.json").read_text(encoding="utf-8"))
    return int(cfg["input_estimate"]["chars_per_token"])


CPT = chars_per_token()


def tokens(text: str) -> int:
    """The repo's input estimate (config/harness.json input_estimate), without its per-message
    margin."""
    return math.ceil(len(text) / CPT)


def header(source_id: str) -> str:
    return f"Source {source_id} (cite it by this id and these line numbers):"


def render(source_id: str, lines: list[str], keep: set[int] | None) -> str:
    """The source as an operator would read it: `N: line`, dropped runs folded into one marker."""
    out = [header(source_id)]
    gap_start = None
    for n, line in enumerate(lines, 1):
        if keep is None or n in keep:
            if gap_start is not None:
                out.append(f"[lines {gap_start}-{n - 1} omitted by the stage-0 filter]")
                gap_start = None
            out.append(f"{n}: {line}")
        elif gap_start is None:
            gap_start = n
    if gap_start is not None:
        out.append(f"[lines {gap_start}-{len(lines)} omitted by the stage-0 filter]")
    return "\n".join(out)


def load(incident: str) -> dict:
    truth = json.loads((CORPUS / incident / "truth.json").read_text(encoding="utf-8"))
    text = (CORPUS / incident / truth["file"]).read_text(encoding="utf-8")
    lines = split_lines(text)
    assert len(lines) == truth["n_lines"], incident
    scores_path = LAYA / f"{incident}.json"
    scores = json.loads(scores_path.read_text(encoding="utf-8")) if scores_path.exists() else None
    return {"id": incident, "truth": truth, "lines": lines, "scores": scores}


def finish(row: dict) -> dict:
    row["recall"] = row["evidence_kept"] / row["evidence"]
    row["tokens_removed"] = 1 - row["tokens_after"] / row["tokens_before"]
    if row["estimated"]:
        # the high bound of tokens after is the low bound of tokens removed
        row["tokens_removed_95ci"] = [
            1 - row["tokens_after_high"] / row["tokens_before"],
            1 - row["tokens_after_low"] / row["tokens_before"],
        ]
    return row


def measure(inc: dict, keep: set[int] | None) -> dict:
    """A or B: every line known, so everything is exact."""
    lines, truth = inc["lines"], inc["truth"]
    ev = [e["line"] for e in truth["evidence"]]
    dec = [d["line"] for d in truth["decoys"]]
    kept_ev = ev if keep is None else [n for n in ev if n in keep]
    kept_dec = dec if keep is None else [n for n in dec if n in keep]
    return finish(
        {
            "evidence": len(ev),
            "evidence_kept": len(kept_ev),
            "evidence_missed": sorted(set(ev) - set(kept_ev)),
            "decoys": len(dec),
            "decoys_kept": len(kept_dec),
            "tokens_before": tokens(render(inc["id"], lines, None)),
            "tokens_after": tokens(render(inc["id"], lines, keep)),
            "estimated": False,
        }
    )


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return 0.0, 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, max(0.0, mid - half), min(1.0, mid + half)


def line_chars(n: int, line: str) -> int:
    return len(f"{n}: {line}") + 1


def laya_measure(inc: dict, form: str, threshold: float, also: set[int] | None = None) -> dict:
    """C or C2, or D when `also` holds B's lines.

    Recall and decoys are exact: every chunk that holds a labeled line was scored. Tokens after
    the filter are estimated: lines inside labeled chunks count exactly; every other line counts
    with the share of sampled chunks at or above the threshold (95% Wilson interval). Gap markers
    are ignored here."""
    lines, truth, s = inc["lines"], inc["truth"], inc["scores"]
    key = FORMS[form]
    also = also or set()
    region: set[int] = set()
    kept: set[int] = set()
    for c in s["chunks"]:
        if c["why"] == "label":
            span = range(c["start"], c["end"] + 1)
            region.update(span)
            if c[key] >= threshold:
                kept.update(span)
    kept |= also & region
    sample = [c for c in s["chunks"] if c["why"] == "sample"]
    k = sum(1 for c in sample if c[key] >= threshold)
    p, lo, hi = wilson(k, len(sample))
    head = len(header(inc["id"])) + 1
    exact_chars = head + sum(line_chars(n, lines[n - 1]) for n in kept)
    sure_chars = sum(line_chars(n, lines[n - 1]) for n in also - region)
    rest_chars = sum(
        line_chars(n, x) for n, x in enumerate(lines, 1) if n not in region and n not in also
    )

    def est(share: float) -> int:
        return math.ceil((exact_chars + sure_chars + share * rest_chars) / CPT)

    ev = [e["line"] for e in truth["evidence"]]
    dec = [d["line"] for d in truth["decoys"]]
    kept_ev = [n for n in ev if n in kept]
    return finish(
        {
            "evidence": len(ev),
            "evidence_kept": len(kept_ev),
            "evidence_missed": sorted(set(ev) - set(kept_ev)),
            "decoys": len(dec),
            "decoys_kept": sum(1 for n in dec if n in kept),
            "sampled_chunks": len(sample),
            "sampled_kept": k,
            "tokens_before": tokens(render(inc["id"], lines, None)),
            "tokens_after": est(p),
            "tokens_after_low": est(lo),
            "tokens_after_high": est(hi),
            "estimated": True,
        }
    )


def pool(rows: list[dict]) -> dict:
    s = {
        k: sum(r[k] for r in rows)
        for k in (
            "evidence",
            "evidence_kept",
            "decoys",
            "decoys_kept",
            "tokens_before",
            "tokens_after",
        )
    }
    s["estimated"] = any(r["estimated"] for r in rows)
    if s["estimated"]:
        for k in ("tokens_after_low", "tokens_after_high"):
            s[k] = sum(r.get(k, r["tokens_after"]) for r in rows)
    return finish(s)


def evidence_scores(incs: list[dict], form: str) -> list[dict]:
    """For each evidence line, the best score among the chunks that hold it."""
    key = FORMS[form]
    out = []
    for inc in incs:
        for e in inc["truth"]["evidence"]:
            n = e["line"]
            best = max(c[key] for c in inc["scores"]["chunks"] if c["start"] <= n <= c["end"])
            out.append({"incident": inc["id"], "line": n, "best_score": best, "note": e["note"]})
    return out


def pick_threshold(incs: list[dict], form: str) -> float:
    """Highest threshold with 100% dev recall: the lowest of the evidence lines' best scores."""
    return min(r["best_score"] for r in evidence_scores(incs, form))


def results_for(inc: dict, thresholds: dict) -> dict[str, dict]:
    b = keyword_kept(inc["lines"])
    out = {"A": measure(inc, None), "B": measure(inc, b)}
    if inc["scores"] is not None and thresholds:
        for form, t in thresholds.items():
            out[form] = laya_measure(inc, form, t)
        out["D"] = laya_measure(inc, "C", thresholds["C"], also=b)
        out["D2"] = laya_measure(inc, "C2", thresholds["C2"], also=b)
    return out


def sweep(incs: list[dict], form: str) -> list[dict]:
    rows = []
    for t in GRID:
        p = pool([laya_measure(i, form, t) for i in incs])
        rows.append({"threshold": t, "recall": p["recall"], "tokens_removed": p["tokens_removed"]})
    return rows


def score_spread(incs: list[dict], form: str) -> dict:
    key = FORMS[form]
    sample = sorted(c[key] for i in incs for c in i["scores"]["chunks"] if c["why"] == "sample")
    q = lambda f: sample[min(len(sample) - 1, int(f * len(sample)))]  # noqa: E731
    return {
        "n": len(sample),
        "min": sample[0],
        "p10": q(0.1),
        "median": q(0.5),
        "p90": q(0.9),
        "max": sample[-1],
    }


def laya_cost(incs: list[dict]) -> list[dict]:
    rows = []
    for inc in incs:
        s = inc["scores"]
        row = {
            k: s[k]
            for k in (
                "n_lines",
                "n_chunks_total",
                "n_chunks_scored",
                "state_room_tokens",
                "load_ms",
                "run_ms",
                "ms_per_chunk",
                "peak_rss_mb",
            )
        }
        row["projected_full_run_s"] = round(s["n_chunks_total"] * s["ms_per_chunk"] / 1000)
        row["truncated_chunks"] = sum(1 for c in s["chunks"] if c["truncated"])
        rows.append({"id": inc["id"]} | row)
    return rows


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def ci(r: dict) -> str:
    if not r["estimated"]:
        return ""
    lo, hi = r["tokens_removed_95ci"]
    return f" ({pct(lo)} to {pct(hi)})"


def table(title: str, results: dict[str, dict[str, dict]], names: list[str]) -> str:
    out = [
        f"### {title}",
        "",
        "| Filter | Incident | Evidence kept | Recall | Tokens before | Tokens after | Removed "
        "| Decoys kept |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for f, per in results.items():
        for name in names + ["pooled"]:
            r = per[name]
            out.append(
                f"| {f} | {name} | {r['evidence_kept']}/{r['evidence']} | {pct(r['recall'])} | "
                f"{r['tokens_before']:,} | {'~' if r['estimated'] else ''}{r['tokens_after']:,} | "
                f"{pct(r['tokens_removed'])}{ci(r)} | {r['decoys_kept']}/{r['decoys']} |"
            )
    return "\n".join(out)


def main() -> int:
    dev_only = "--dev-only" in sys.argv
    dev = [load(i) for i in DEV]
    test = [] if dev_only else [load(i) for i in TEST]
    have_laya = all(i["scores"] is not None for i in dev + test)
    thresholds = {f: pick_threshold(dev, f) for f in FORMS} if have_laya else {}

    summary: dict = {"synthetic": True, "chars_per_token": CPT, "thresholds_from_dev": thresholds}
    for split, incs in (("dev", dev), ("test", test)):
        if not incs:
            continue
        per_filter: dict[str, dict] = {}
        for inc in incs:
            for f, row in results_for(inc, thresholds).items():
                per_filter.setdefault(f, {})[inc["id"]] = row
        for per in per_filter.values():
            per["pooled"] = pool([per[i["id"]] for i in incs])
        summary[split] = per_filter
        print(table(f"{split} incidents", per_filter, [i["id"] for i in incs]))
        print()
    if have_laya:
        everything = dev + test
        summary["laya_cost"] = laya_cost(everything)
        summary["evidence_scores"] = {f: evidence_scores(everything, f) for f in FORMS}
        summary["sample_score_spread"] = {f: score_spread(everything, f) for f in FORMS}
        summary["sweep_dev"] = {f: sweep(dev, f) for f in FORMS}
        if test:
            summary["sweep_test_post_hoc"] = {f: sweep(test, f) for f in FORMS}
        print("thresholds from dev:", json.dumps(thresholds))
        print("routine-chunk score spread:", json.dumps(summary["sample_score_spread"]))
        for f in FORMS:
            for split in ("sweep_dev", "sweep_test_post_hoc"):
                if split in summary:
                    print(
                        f"{split}, {f}: "
                        + "; ".join(
                            f"t={r['threshold']:.2f} recall={pct(r['recall'])} "
                            f"removed={pct(r['tokens_removed'])}"
                            for r in summary[split][f]
                        )
                    )
        for row in summary["laya_cost"]:
            print("cost:", json.dumps(row))
    name = "summary_dev_only.json" if dev_only else "summary.json"
    out = HERE / "results" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
