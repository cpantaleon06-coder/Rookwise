"""scripts/run_benchmark.py on the synthetic incident of test_run_incident.py (one dev
copy, one test copy), the stub transport and a fake clock. No network, no live call, no
gitignored logs; every file goes to tmp_path."""

import asyncio
import copy
import importlib.util
import json
import random
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from harness_support import FakeClock
from test_run_incident import BUNDLE, FAKE_KEY, SOURCES, TRUTH

ROOT = Path(__file__).resolve().parents[1]
DEV, TEST = "inc-dev", "inc-test"
TRUTHS = {
    DEV: TRUTH.model_copy(update={"incident_id": DEV, "split": "dev"}),
    TEST: TRUTH.model_copy(update={"incident_id": TEST, "split": "test"}),
}


@pytest.fixture
def bench(monkeypatch, tmp_path):
    path = ROOT / "scripts" / "run_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_benchmark", path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules["run_benchmark"] = loaded
    spec.loader.exec_module(loaded)
    incident = loaded.run_incident
    # These tests must never read .env, and the stub sizes must not depend on a local file.
    monkeypatch.setattr(loaded, "load_dotenv", lambda *a, **k: pytest.fail(".env was read"))
    monkeypatch.setattr(incident, "RECORDED_RUN", tmp_path / "none.json")
    monkeypatch.setenv("NEBIUS_API_KEY", FAKE_KEY)
    real = incident.Harness

    def harness(*args, **kwargs):  # rate limits and backoff never sleep for real
        return real(*args, clock=FakeClock(), rng=random.Random(0), **kwargs)

    monkeypatch.setattr(incident, "Harness", harness)
    return loaded


def _config(bench, incidents=(DEV, TEST), configurations=("a", "c"), repeats=2):
    config = copy.deepcopy(bench.run_incident.load_benchmark_config())
    config["benchmark"].update(
        incidents=list(incidents),
        configurations=list(configurations),
        repeats=repeats,
        caps_usd={"a": "0.500000", "b": "1.000000", "c": "1.000000"},
    )
    return config


class Spy:
    """run_incident.run, counting the calls of each mode; `inflate` adds to what a record
    run reports as spent; `fail_on` makes that record run raise."""

    def __init__(self, bench, inflate="0", fail_on=None):
        self.run = bench.run_incident.run
        self.modes = []
        self.inflate = Decimal(inflate)
        self.fail_on = fail_on
        self.count = 0

    async def __call__(self, mode, incident_id, **kwargs):
        self.modes.append(mode)
        if mode == "record":
            self.count += 1
            if self.count == self.fail_on:
                raise RuntimeError("[stub] the run broke")
        report, events, calls = await self.run(mode, incident_id, **kwargs)
        if mode == "record" and self.inflate:
            report = {**report, "spent_usd": str(Decimal(report["spent_usd"]) + self.inflate)}
        return report, events, calls


def _go(bench, tmp_path, config, *, runner=None, lines=None, **kwargs):
    incident = bench.run_incident
    sizes = incident.stub_output_tokens()["tokens"]
    transport = incident.stub_transport(
        BUNDLE, ["ticket.md", "runbook.md"], sizes, incident.load_config(env={})
    )
    options = {
        "split": "dev",
        "live": False,
        "approve_total_usd": None,
        "freeze_confirmed": False,
    } | kwargs
    return asyncio.run(
        bench.benchmark(
            config,
            results_dir=tmp_path / "results",
            cassette_dir=tmp_path / "cassettes",
            tmp_dir=tmp_path,
            loader=lambda incident_id: (BUNDLE, TRUTHS[incident_id]),
            truth_loader=TRUTHS.__getitem__,
            runner=runner or Spy(bench),
            transport=transport,
            say=(lines if lines is not None else []).append,
            **options,
        )
    )


def _results(tmp_path):
    return sorted(p.name for p in (tmp_path / "results" / "runs").glob("*.json"))


def _predicted(lines):
    line = next(line for line in lines if line.startswith("Predicted total"))
    return Decimal(line.split("USD ")[1].split(";")[0])


def test_the_plan_is_config(bench):
    config = bench.run_incident.load_benchmark_config()
    plan = bench.load_plan(config)
    assert plan["configurations"] == ["a", "b", "c"] and plan["repeats"] == 2
    assert len(plan["incidents"]) == 6
    assert plan["results_dir"] == "benchmarks/results"
    assert bench.cap_for(config, "a") == config["benchmark"]["caps_usd"]["a"]


def test_without_live_it_only_prints_the_predicted_total(bench, tmp_path):
    lines, spy = [], Spy(bench)
    code = _go(bench, tmp_path, _config(bench), runner=spy, lines=lines)
    assert code == 0 and set(spy.modes) == {"estimate"}
    # One estimate per (incident, configuration), not per repeat.
    assert spy.modes == ["estimate", "estimate"]
    assert lines[0] == "Planned runs: 4 (dev split); done: 0; to run: 4."
    assert _predicted(lines) > 0
    assert any("worst case" in line and "USD 3.000000" in line for line in lines)
    assert not (tmp_path / "results").exists()


def test_live_runs_need_an_approval_of_at_least_the_predicted_total(bench, tmp_path):
    lines = []
    _go(bench, tmp_path, _config(bench), lines=lines)
    total = _predicted(lines)
    for approve in (None, total - Decimal("0.000001")):
        lines, spy = [], Spy(bench)
        code = _go(
            bench,
            tmp_path,
            _config(bench),
            runner=spy,
            lines=lines,
            live=True,
            approve_total_usd=approve,
        )
        assert code == 2 and "record" not in spy.modes
        assert lines[-1].startswith("Refused: live runs need --approve-total-usd")
        assert not (tmp_path / "results").exists()


def test_a_live_dev_run_writes_metrics_only_results_and_the_summary(bench, tmp_path):
    lines, spy = [], Spy(bench)
    code = _go(
        bench,
        tmp_path,
        _config(bench),
        runner=spy,
        lines=lines,
        live=True,
        approve_total_usd=Decimal("10"),
    )
    assert code == 0 and spy.modes.count("record") == 4
    assert _results(tmp_path) == [
        f"{DEV}__a__r1.json",
        f"{DEV}__a__r2.json",
        f"{DEV}__c__r1.json",
        f"{DEV}__c__r2.json",
    ]
    result = json.loads((tmp_path / "results" / "runs" / f"{DEV}__a__r1.json").read_text())
    assert (result["incident_id"], result["split"], result["configuration"], result["repeat"]) == (
        DEV,
        "dev",
        "a",
        1,
    )
    assert {"commit", "dirty", "config_sha256", "spent_usd", "score", "retries"} <= set(result)
    assert Decimal(result["spent_usd"]) <= Decimal(result["cap_usd"])
    # Metrics only: no prompt, source, claim or note text.
    text = json.dumps(result)
    for secret in [*SOURCES.values(), "[stub]", "SECRET-TRUTH-MARKER", "Investigate"]:
        assert secret.strip().splitlines()[0] not in text
    dev_csv = (tmp_path / "results" / "summary-dev.csv").read_text().splitlines()
    assert dev_csv[0].startswith("split,configuration,runs,incidents,")
    assert [row.split(",")[:3] for row in dev_csv[1:]] == [["dev", "a", "2"], ["dev", "c", "2"]]
    assert (tmp_path / "results" / "summary-test.csv").read_text().count("\n") == 1  # header
    summary = (tmp_path / "results" / "summary.md").read_text()
    assert "## Dev split" in summary and "## Test split\n\nNo runs yet." in summary
    # The cassettes, which hold prompt text, are apart from the results.
    assert sorted(p.name for p in (tmp_path / "cassettes").glob("*.json")) == _results(tmp_path)


def test_a_rerun_skips_the_runs_whose_result_exists(bench, tmp_path):
    config = _config(bench)
    _go(bench, tmp_path, config, live=True, approve_total_usd=Decimal("10"))
    lines, spy = [], Spy(bench)
    code = _go(
        bench, tmp_path, config, runner=spy, lines=lines, live=True, approve_total_usd=Decimal("10")
    )
    assert code == 0 and spy.modes == [] and lines[0].endswith("done: 4; to run: 0.")
    (tmp_path / "results" / "runs" / f"{DEV}__c__r2.json").unlink()
    lines, spy = [], Spy(bench)
    _go(
        bench, tmp_path, config, runner=spy, lines=lines, live=True, approve_total_usd=Decimal("10")
    )
    assert spy.modes == ["estimate", "record"] and len(_results(tmp_path)) == 4
    assert any(line.startswith(f"Running {DEV}__c__r2") for line in lines)


def test_test_split_runs_are_refused_until_the_freeze_is_confirmed(bench, tmp_path):
    for split in ("test", "all"):
        lines, spy = [], Spy(bench)
        code = _go(
            bench,
            tmp_path,
            _config(bench),
            runner=spy,
            lines=lines,
            split=split,
            live=True,
            approve_total_usd=Decimal("10"),
        )
        assert code == 2 and "record" not in spy.modes
        assert lines[-1].startswith(f"Refused: {TEST} are test-split incidents")
    lines, spy = [], Spy(bench)
    code = _go(
        bench,
        tmp_path,
        _config(bench),
        runner=spy,
        lines=lines,
        split="all",
        live=True,
        approve_total_usd=Decimal("10"),
        freeze_confirmed=True,
    )
    assert code == 0 and spy.modes.count("record") == 8
    summary = (tmp_path / "results" / "summary.md").read_text()
    dev, test = summary.split("## Test split")
    assert "## Dev split" in dev and "| a | 2 | 1 |" in dev and "| a | 2 | 1 |" in test
    test_csv = (tmp_path / "results" / "summary-test.csv").read_text().splitlines()
    assert [row.split(",")[:2] for row in test_csv[1:]] == [["test", "a"], ["test", "c"]]
    dev_csv = (tmp_path / "results" / "summary-dev.csv").read_text()
    assert ",test," not in dev_csv and "test," not in dev_csv.splitlines()[1]


def test_it_stops_before_a_run_that_would_pass_the_approved_total(bench, tmp_path):
    lines = []
    _go(bench, tmp_path, _config(bench), lines=lines)
    total = _predicted(lines)
    # Each record run reports USD 0.10 more than predicted, so the approval runs out.
    lines, spy = [], Spy(bench, inflate="0.10")
    code = _go(
        bench,
        tmp_path,
        _config(bench),
        runner=spy,
        lines=lines,
        live=True,
        approve_total_usd=total + Decimal("0.15"),
    )
    assert code == 3 and 0 < spy.modes.count("record") < 4
    assert len(_results(tmp_path)) == spy.modes.count("record")
    assert lines[-1].startswith("Stopped before ")
    assert (tmp_path / "results" / "summary.md").exists()


def test_a_run_that_raises_stops_the_benchmark_and_writes_nothing_for_it(bench, tmp_path):
    lines, spy = [], Spy(bench, fail_on=2)
    code = _go(
        bench,
        tmp_path,
        _config(bench),
        runner=spy,
        lines=lines,
        live=True,
        approve_total_usd=Decimal("10"),
    )
    assert code == 3 and spy.modes.count("record") == 2
    assert _results(tmp_path) == [f"{DEV}__a__r1.json"]
    assert lines[-1] == f"Stopped: {DEV}__a__r2 raised RuntimeError: [stub] the run broke"


def test_test_results_from_two_commits_are_flagged(bench):
    def result(commit, configuration="a"):
        return {
            "incident_id": TEST,
            "split": "test",
            "configuration": configuration,
            "repeat": 1,
            "commit": commit,
            "spent_usd": "0.010000",
            "partial": False,
            "wall_clock_s": 1.0,
            "operator_tasks": {"ok": 1, "total": 1},
            "retries": {"retried_attempts": 0},
            "trimmed_citations": 0,
            "score": {
                "diagnosis_correct": True,
                "category_correct": True,
                "evidence_recall": 1.0,
                "citation_verified_rate": 1.0,
                "citation_first_pass_validity": 1.0,
            },
        }

    results = [result("a" * 40), result("b" * 40)]
    text = bench._markdown(bench.summarize(results), results)
    assert "WARNING: these test results come from more than one commit" in text
    one = [result("a" * 40)]
    assert "WARNING" not in bench._markdown(bench.summarize(one), one)


def test_the_cli_never_starts_a_live_run_by_accident(bench, monkeypatch, capsys):
    monkeypatch.delenv("HARNESS_MODE", raising=False)
    assert bench.main(["--live", "--approve-total-usd", "1"]) == 2
    assert "Set HARNESS_MODE=record" in capsys.readouterr().out
    assert bench.main(["--approve-total-usd", "lots"]) == 2
    assert "must be a positive amount" in capsys.readouterr().out
