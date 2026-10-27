import json

import pytest
import results_json as rj
import verify_benchmark as vb
from bench_fixtures import write_results


@pytest.fixture
def results(tmp_path):
    root = write_results(tmp_path / "results")
    return rj.build(vb.load_runs(root / "runs"))


@pytest.mark.parametrize(
    ("value", "text"),
    [(0.7055, "0.706"), (0.70503, "0.705"), (0.2, "0.200"), ("0.249995", "0.250"), (1, "1.000")],
)
def test_three_rounds_half_up(value, text):
    assert rj.three(value) == text


def test_aggregates_test_first_then_a_b_c(results):
    keys = [(a["split"], a["configuration"]) for a in results["aggregates"]]
    assert keys == [
        ("test", "a"),
        ("test", "b"),
        ("test", "c"),
        ("dev", "a"),
        ("dev", "b"),
        ("dev", "c"),
    ]
    first = results["aggregates"][0]
    assert first["label"] == "(a) hierarchy"
    assert first["diagnosis_correct"] == 2
    assert first["spent_usd_total"] == "0.600000"
    assert first["spent_usd_mean"] == "0.200000"
    assert first["wall_clock_s_total"] == 600.0


def test_runs_have_one_entry_per_file(results):
    assert len(results["runs"]) == 18
    first = results["runs"][0]
    assert (first["split"], first["configuration"], first["incident_id"]) == ("test", "a", "inc-02")
    assert first["spent_usd"] == "0.300000"
    assert first["coverage"] == 0.9
    assert first["slices_read"] == 7


def test_markdown_table(results):
    lines = rj.markdown_table(results).splitlines()
    assert lines[0] == (
        "| Configuration | Split | Correct (n of 3) | Evidence recall | Coverage "
        "| Real cost per run (USD) |"
    )
    assert lines[2] == "| (a) hierarchy | test | 2 of 3 | 0.500 | 0.900 | 0.200 |"
    assert lines[3] == "| (b) single Ultra | test | 0 of 3 | 0.250 | 0.200 | 0.400 |"
    assert lines[4] == "| (c) single Lightning | test | 1 of 3 | 0.167 | 0.700 | 0.120 |"
    assert lines[5].startswith("| (a) hierarchy | dev |")
    assert len(lines) == 8


def test_main_writes_json_and_prints_table(tmp_path, capsys):
    root = write_results(tmp_path / "results")
    out = tmp_path / "out" / "results.json"
    assert rj.main(["--results-dir", str(root), "--out", str(out), "--markdown"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["aggregates"]) == 6
    assert "| (c) single Lightning | dev | 1 of 3 |" in capsys.readouterr().out


def test_main_without_runs_fails(tmp_path):
    (tmp_path / "runs").mkdir()
    assert rj.main(["--results-dir", str(tmp_path), "--out", str(tmp_path / "x.json")]) == 1
