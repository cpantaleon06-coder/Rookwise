"""scripts/classify_citation_failures.py on synthetic sources and reports. Offline."""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    "# SYNTHETIC header\n"
    "02:12:44 INFO deploy.agent received config_version=42\n"
    "02:12:45 INFO config.diff db.pool.max_connections: 50 -> 5\n"
    "02:13:40 WARN db.pool wait waited_ms=850 active=5 max=5\n"
    "02:14:10 ERROR db.pool timeout active=5 max=5 queued=31\n"
    "02:14:33 INFO pg-primary connections=9 of 200\n"
    "02:16:30 INFO pg-primary connections=8 of 200\n"
    "02:21:15 INFO rollback requested to config_version=41\n"
)


def _script():
    path = ROOT / "scripts" / "classify_citation_failures.py"
    spec = importlib.util.spec_from_file_location("classify_citation_failures", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["classify_citation_failures"] = module
    spec.loader.exec_module(module)
    return module


def _citation(quote, start, end, model="nemotron-3.5-lightning", reason="quote_not_found"):
    status = "verified" if reason == "ok" else "failed"
    return {
        "claim_id": f"t-1:c{start}",
        "model": model,
        "source_id": "log",
        "line_start": start,
        "line_end": end,
        "quote": quote,
        "reason": reason,
        "status": status,
    }


def test_a_quote_on_other_lines_is_a_line_offset_with_its_true_line_and_distance():
    module = _script()
    row = module.classify(_citation("db.pool.max_connections: 50 -> 5", 5, 5), SOURCE)
    assert row["class"] == "line_offset"
    assert (row["true_line_start"], row["true_line_end"], row["distance"]) == (3, 3, -2)


def test_a_one_line_quote_over_two_lines_is_found_with_its_span():
    module = _script()
    quote = "max=5 02:14:10 ERROR db.pool timeout"  # the end of line 4, the start of line 5
    row = module.classify(_citation(quote, 7, 8), SOURCE)
    assert row["class"] == "line_offset"
    assert (row["true_line_start"], row["true_line_end"], row["distance"]) == (4, 5, -3)


def test_the_nearest_occurrence_wins():
    module = _script()
    row = module.classify(_citation("connections=", 7, 7), SOURCE)
    assert (row["class"], row["true_line_start"], row["distance"]) == ("line_offset", 7, 0)


def test_a_slightly_changed_quote_is_altered_with_its_ratio_and_nearest_line():
    module = _script()
    # The timestamps were dropped and the separator changed: no exact match.
    quote = "INFO config.diff db.pool.max_connections 50 -> 5"
    row = module.classify(_citation(quote, 2, 2), SOURCE)
    assert row["class"] == "altered"
    assert row["ratio"] >= 0.8 and row["nearest_line"] == 3


def test_a_quote_that_is_nowhere_near_is_absent():
    module = _script()
    row = module.classify(_citation("kernel panic: unable to mount root fs", 2, 2), SOURCE)
    assert row["class"] == "absent" and row["ratio"] < 0.8


def test_range_widths_are_bucketed_and_counted():
    module = _script()
    assert [module.width_bucket(4, e) for e in (4, 5, 7, 8, 30)] == [
        "1 line",
        "2 to 4",
        "2 to 4",
        "5 or more",
        "5 or more",
    ]
    report = {
        "citations": [
            _citation("db.pool.max_connections: 50 -> 5", 5, 5),  # 1 line, line_offset
            _citation("rollback requested to config_version=41", 2, 4),  # 2 to 4, line_offset
            _citation("no such text in this source at all here", 1, 6),  # 5 or more, absent
            _citation(
                "02:12:45 INFO config.diff db.pool.max_connections: 50 -> 5", 3, 3, reason="ok"
            ),
            _citation("x", 99, 99, reason="line_out_of_range"),
        ]
    }
    rows, other = module.classify_report(report, {"log": SOURCE})
    assert [(r["width"], r["class"]) for r in rows] == [
        ("1 line", "line_offset"),
        ("2 to 4", "line_offset"),
        ("5 or more", "absent"),
    ]
    assert other == {"line_out_of_range": 1}  # verified citations are not counted at all
    text = module.render(rows, other)
    assert "| 1 line | 1 | 0 | 0 | 1 |" in text
    assert "| 2 to 4 | 1 | 0 | 0 | 1 |" in text
    assert "| 5 or more | 0 | 0 | 1 | 1 |" in text
    assert "| nemotron-3.5-lightning | 2 | 0 | 1 | 3 |" in text
    assert "line_out_of_range 1" in text


def test_the_cli_reads_a_report_and_the_scenario_sources(tmp_path, monkeypatch, capsys):
    module = _script()
    scenario = tmp_path / "scenario"
    scenario.mkdir()
    (scenario / "log.txt").write_text(SOURCE, encoding="utf-8")
    (scenario / "scenario.json").write_text(json.dumps({"sources": {"log": "log.txt"}}), "utf-8")
    report = tmp_path / "report.json"
    citation = _citation("db.pool.max_connections: 50 -> 5", 5, 5, model="nemotron-3-super")
    report.write_text(json.dumps({"citations": [citation]}), encoding="utf-8")
    argv = ["x", "--report", str(report), "--scenario-dir", str(scenario)]
    monkeypatch.setattr(sys, "argv", argv)
    assert module.main() == 0
    out = capsys.readouterr().out
    assert "| line_offset | 1 |" in out and "| nemotron-3-super | 1 | 0 | 0 | 1 |" in out
    assert "true lines 3-3, distance -2" in out


def test_an_old_report_without_citation_detail_is_refused(tmp_path, monkeypatch, capsys):
    module = _script()
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"claims": []}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", "--report", str(report)])
    assert module.main() == 2
    assert "no `citations` list" in capsys.readouterr().out
