from decimal import Decimal
from pathlib import Path

import pytest
import verify_benchmark as vb
from bench_fixtures import edit_run, write_results, write_summary

REAL_RESULTS = Path(__file__).resolve().parents[2] / "benchmarks" / "results"


@pytest.fixture
def results(tmp_path):
    return write_results(tmp_path / "results")


def checks_by_name(results_dir):
    runs = vb.load_runs(results_dir / "runs")
    out = vb.run_checks(results_dir, runs, vb.aggregate(runs), known_good=False)
    return {c.name: c for c in out}


def test_aggregate_recomputes_each_group(results):
    aggregates = {
        (a.split, a.configuration): a for a in vb.aggregate(vb.load_runs(results / "runs"))
    }
    assert [k for k in aggregates] == [(s, c) for s in ("dev", "test") for c in ("a", "b", "c")]
    a = aggregates[("test", "a")]
    assert (a.runs, a.correct) == (3, 2)
    assert a.evidence_recall_mean == pytest.approx(0.5)
    assert a.coverage_mean == pytest.approx(0.9)
    assert a.spent_usd_total == Decimal("0.600000")
    assert a.spent_usd_mean == Decimal("0.2")
    assert a.wall_clock_s_total == pytest.approx(600.0)
    assert aggregates[("dev", "b")].spent_usd_total == Decimal("1.200001")


def test_spent_usd_may_be_a_number(results):
    edit_run(results, "inc-01__a__r1.json", spent_usd=0.25)
    runs = {r.name: r for r in vb.load_runs(results / "runs")}
    assert runs["inc-01__a__r1.json"].spent_usd == Decimal("0.25")


def test_consistent_fixture_passes(results, capsys):
    assert vb.main(["--results-dir", str(results), "--skip-known-good"]) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    assert out.count("PASS") == 6
    assert "distinct commits (2):" in out
    assert "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  (dev a, dev b, dev c)" in out


def test_dirty_run_fails(results):
    edit_run(results, "inc-04__c__r1.json", dirty=True)
    check = checks_by_name(results)["no run file has dirty true"]
    assert not check.passed
    assert check.details == ["inc-04__c__r1.json"]


def test_spent_over_cap_fails(results):
    edit_run(results, "inc-02__b__r1.json", spent_usd="0.500001")
    check = checks_by_name(results)["spent_usd <= cap_usd in every run file"]
    assert not check.passed
    assert "inc-02__b__r1.json" in check.details[0]


def test_spent_equal_to_cap_passes(results):
    edit_run(results, "inc-02__b__r1.json", spent_usd="0.5")
    assert checks_by_name(results)["spent_usd <= cap_usd in every run file"].passed


def test_missing_file_fails_count_and_group(results, capsys):
    (results / "runs" / "inc-06__c__r1.json").unlink()
    checks = checks_by_name(results)
    assert not checks["exactly 18 run files"].passed
    group = checks["3 runs per (split, configuration)"]
    assert not group.passed
    assert group.details == ["test c: 2 runs"]
    assert vb.main(["--results-dir", str(results), "--skip-known-good"]) == 1


def test_unexpected_group_fails(results):
    edit_run(results, "inc-01__a__r1.json", configuration="z")
    group = checks_by_name(results)["3 runs per (split, configuration)"]
    assert "unexpected group dev z: 1 runs" in group.details


@pytest.mark.parametrize(
    ("column", "value", "passed"),
    [
        ("evidence_recall_mean", "0.50009", True),  # within 1e-4
        ("evidence_recall_mean", "0.5002", False),
        ("coverage_mean", "0.8998", False),
        ("diagnosis_correct_rate", "0.6667", True),
        ("diagnosis_correct_rate", "0.5", False),
        ("spent_usd_total", "0.600001", True),  # within 1e-6
        ("spent_usd_total", "0.600002", False),
        ("spent_usd_mean", "0.200002", False),
        ("wall_clock_s_mean", "200.0001", True),
        ("wall_clock_s_mean", "201", False),
        ("runs", "4", False),
        ("commits", "9999999", False),
        ("commits", "", False),
    ],
)
def test_summary_comparison_tolerances(results, column, value, passed):
    write_summary(results, "test", {("test", "a"): {column: value}})
    check = checks_by_name(results)["summary-test.csv matches the run files"]
    assert check.passed is passed
    if not passed:
        assert check.details[0].startswith("test a:")


def test_summary_missing_row_and_file(results):
    lines = (results / "summary-dev.csv").read_text(encoding="utf-8").splitlines()
    (results / "summary-dev.csv").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    (results / "summary-test.csv").unlink()
    checks = checks_by_name(results)
    assert checks["summary-dev.csv matches the run files"].details == [
        "dev c: no row in summary-dev.csv"
    ]
    assert not checks["summary-test.csv matches the run files"].passed


def test_known_good_comparison(results):
    aggregates = vb.aggregate(vb.load_runs(results / "runs"))
    good = {("test", "a"): {"correct": 2, "spent_usd_total": 0.6, "coverage_mean": 0.9}}
    assert vb.check_known_good(aggregates, good).passed
    bad = {("test", "a"): {"correct": 3, "evidence_recall_mean": 0.4}}
    check = vb.check_known_good(aggregates, bad)
    assert not check.passed
    assert len(check.details) == 2


def test_table_lists_every_group(results):
    table = vb.format_table(vb.aggregate(vb.load_runs(results / "runs")))
    lines = table.splitlines()
    assert lines[0].split()[:4] == ["split", "config", "runs", "correct"]
    assert len(lines) == 8
    assert "1.200001" in table


@pytest.mark.skipif(not (REAL_RESULTS / "runs").is_dir(), reason="real results not present")
def test_real_results_pass(capsys):
    assert vb.main([]) == 0
