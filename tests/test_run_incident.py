"""scripts/run_incident.py on a small synthetic bundle and the stub transport. No network,
no gitignored logs, no live call."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from rookwise.evidence import EvidenceBundle
from rookwise.incidents import GroundTruth

ROOT = Path(__file__).resolve().parents[1]
FAKE_KEY = "fake-key-for-incident-tests"

# SYNTHETIC incident: every file says so; nothing here comes from benchmarks/incidents/.
LOG = "".join(
    f"2026-03-04T03:{n:02d}:00Z INFO api request ok latency_ms={40 + n}\n" for n in range(40)
)
SOURCES = {
    "ticket.md": "# SYNTHETIC ticket\nAlert: the api is slow since 03:20 UTC.\n",
    "runbook.md": "# SYNTHETIC runbook\nCheck the latency first.\n",
    "deploy.diff": "--- a/api.conf\n+++ b/api.conf\n-workers = 8\n+workers = 2\n",
    "metrics.csv": "# SYNTHETIC\nminute,latency_ms\n0,40\n1,41\n",
    "logs/api.log": LOG,
}
BUNDLE = EvidenceBundle(sources=SOURCES)
ESSENTIAL = {
    "source_id": "deploy.diff",
    "line_start": 4,
    "line_end": 4,
    "quote": "+workers = 2",
    "note": "[stub] the cause",
}
DECOY = {"source_id": "logs/api.log", "line_start": 1, "line_end": 1, "quote": "INFO", "note": "x"}
TRUTH = GroundTruth.model_validate(
    {
        "synthetic": True,
        "note": "SYNTHETIC",
        "incident_id": "inc-test",
        "split": "dev",
        "difficulty": "easy",
        "root_cause": "The deploy cut the worker pool from 8 to 2 (SECRET-TRUTH-MARKER).",
        "root_cause_category": "bad_config",
        "categories": ["bad_config"],
        "essential_evidence": [ESSENTIAL],
        "supporting_evidence": [],
        "decoys": [DECOY, DECOY],
        "acceptable_remediations": ["Restore 8 workers."],
        "keyword_free_evidence": True,
        "cause_in_deploy_diff": True,
        "misleading_first_hypothesis": None,
        "sources": {k: {"lines": 1, "committed": True} for k in SOURCES},
        "log_lines": 40,
        "seed": 0,
    }
)


@pytest.fixture
def module(monkeypatch):
    path = ROOT / "scripts" / "run_incident.py"
    spec = importlib.util.spec_from_file_location("run_incident", path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules["run_incident"] = loaded
    spec.loader.exec_module(loaded)
    # These tests must never read .env.
    monkeypatch.setattr(loaded, "load_dotenv", lambda *a, **k: pytest.fail(".env was read"))
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    return loaded


def _estimate(module, tmp_path, run_usd="0.50"):
    return asyncio.run(
        module.run(
            "estimate",
            "inc-test",
            bundle=BUNDLE,
            truth=TRUTH,
            run_usd=run_usd,
            cassette=tmp_path / "unused.json",
        )
    )


def test_the_default_cap_is_the_hierarchy_cap_in_config(module):
    config = module.load_benchmark_config()
    assert module.default_cap(config) == "0.100000"
    assert config["context_sources"] == ["ticket.md", "runbook.md"]


def test_stub_outputs_come_from_the_recording_or_are_labeled_placeholders(module, tmp_path):
    missing = module.stub_output_tokens(tmp_path / "none.json")
    assert set(missing["tokens"].values()) == {1000}
    assert all(s.startswith("PLACEHOLDER") for s in missing["source"].values())
    recording = {
        "interactions": [
            {
                "request": {
                    "messages": [{"role": "system", "content": f"You are an operator {n}"}]
                },
                "usage": {"output_tokens": tokens},
            }
            for n, tokens in enumerate((100, 300))
        ]
    }
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(recording), encoding="utf-8")
    found = module.stub_output_tokens(path)
    assert found["tokens"]["operator"] == 200 and found["operator_max"] == 300
    assert found["source"]["operator"].startswith("mean of 2 calls")
    assert found["source"]["diagnosis"].startswith("PLACEHOLDER")


def test_an_estimate_run_reports_cost_refusals_claims_and_the_score(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "RECORDED_RUN", tmp_path / "none.json")
    bodies = []
    stub = module.stub_transport

    def spy(*args, **kwargs):
        inner = stub(*args, **kwargs).handler

        def handle(request):
            bodies.append(request.content.decode("utf-8"))
            return inner(request)

        return module.httpx.MockTransport(handle)

    monkeypatch.setattr(module, "stub_transport", spy)
    report, events, calls = _estimate(module, tmp_path)
    assert report["status"] == "finished" and report["under_cap"]
    assert report["ledger_refusals"] == [] and report["unread_slices"] == []
    assert report["operator_calls_run"] == report["operator_tasks"]["total"] == 5
    assert set(report["director_requests"]) == {"plan", "diagnosis"}
    assert report["director_requests"]["diagnosis"]["input_tokens_estimate"] > 0
    assert report["diagnosis"]["status"] == "audited"
    assert report["diagnosis"]["withdrawn_claims"] == []
    assert report["score"]["citation_first_pass"]["validity"] == 1.0
    # The stub says bad_config but never cites the essential line, so it is not correct.
    assert report["score"]["category_correct"] is True
    assert report["score"]["diagnosis_correct"] is False
    assert report["score"]["evidence_recall"] == 0.0
    assert report["stub_output_tokens"]["source"]["operator"].startswith("PLACEHOLDER")
    for row in report["by_model"].values():
        assert set(row) >= {"usd_real", "usd_predicted", "calls"}
    assert {"director", "director (diagnosis)", "manager", "auditor"} <= set(
        report["outcomes_by_role"]
    )
    # The ticket and the runbook reach the director in full; the ground truth reaches no one.
    assert any(
        "Context, read in full:" in body and "Alert: the api is slow" in body for body in bodies
    )
    assert not any("SECRET-TRUTH-MARKER" in body or "ground_truth" in body for body in bodies)


def test_a_tight_cap_shows_the_ledger_refusals(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "RECORDED_RUN", tmp_path / "none.json")
    report, _, _ = _estimate(module, tmp_path, run_usd="0.02")
    assert report["under_cap"]
    refusals = report["ledger_refusals"]
    assert refusals and all(
        {"requested_usd", "left_usd", "allocation_usd"} <= set(r) for r in refusals
    )


def test_record_writes_a_cassette_that_replays_offline(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "RECORDED_RUN", tmp_path / "none.json")
    monkeypatch.setenv("NEBIUS_API_KEY", FAKE_KEY)
    cassette = tmp_path / "incident.json"
    config = module.load_config(env={})
    sizes = module.stub_output_tokens()["tokens"]
    transport = module.stub_transport(BUNDLE, ["ticket.md", "runbook.md"], sizes, config)
    common = {"bundle": BUNDLE, "truth": TRUTH, "run_usd": "0.50", "cassette": cassette}
    recorded, events, _ = asyncio.run(
        module.run("record", "inc-test", transport=transport, **common)
    )
    assert FAKE_KEY not in cassette.read_text(encoding="utf-8")
    monkeypatch.delenv("NEBIUS_API_KEY")
    replayed, replayed_events, _ = asyncio.run(module.run("replay", "inc-test", **common))
    assert replayed["spent_usd"] == recorded["spent_usd"]
    assert replayed["score"] == recorded["score"]

    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in ("ts", "mode")}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    assert strip(replayed_events) == strip(events)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["inc-01", "record"], "pass --approve-cap 0.100000"),
        (["inc-01", "record", "--approve-cap", "0.50"], "pass --approve-cap 0.100000"),
        (["inc-01", "record", "--run-usd", "0.50", "--approve-cap", "0.10"], "--approve-cap 0.50"),
        (["inc-01", "estimate", "--approve-cap", "0.10"], "for record mode only"),
        (["inc-01", "estimate", "--run-usd", "-1"], "positive amount"),
    ],
)
def test_the_cli_never_starts_a_live_run_by_accident(module, monkeypatch, capsys, argv, message):
    monkeypatch.setenv("HARNESS_MODE", "record")
    monkeypatch.setattr(module, "load_bundle", lambda *a, **k: pytest.fail("a run started"))
    assert module.main(argv) == 2
    assert message in capsys.readouterr().out


def test_an_approved_record_run_still_needs_the_record_mode(module, monkeypatch, capsys):
    monkeypatch.delenv("HARNESS_MODE", raising=False)
    monkeypatch.setattr(module, "load_bundle", lambda *a, **k: pytest.fail("a run started"))
    assert module.main(["inc-01", "record", "--approve-cap", "0.10"]) == 2
    assert "HARNESS_MODE=record" in capsys.readouterr().out


def test_stop_after_plan_makes_only_the_plan_call(module, tmp_path):
    report, events, calls = asyncio.run(
        module.run(
            "estimate",
            "inc-test",
            bundle=BUNDLE,
            truth=TRUTH,
            run_usd="0.50",
            cassette=tmp_path / "unused.json",
            stop_after="plan",
        )
    )
    assert [(c["level"], c["task_id"]) for c in calls] == [("director", "plan")]
    assert report["stop_after"] == "plan"
    assert (report["status"], report["partial"]) == ("cancelled", True)
    assert report["spent_usd"] == report["by_model"]["nemotron-3-ultra"]["usd_real"]
    assert report["operator_calls_run"] == 0 and report["managers"] == []
    assert {u["source_id"] for u in report["unread_slices"]} == set(SOURCES)  # nothing read
    assert "Stopped after the director's plan" in report["notes"][-1]
    finished = events[-1]
    assert finished["type"] == "run_finished"
    assert (finished["payload"]["status"], finished["payload"]["partial"]) == ("cancelled", True)
    assert not any(e["type"] == "budget_allocation" for e in events)


def test_the_cli_passes_stop_after_and_writes_beside_the_full_run(module, monkeypatch, tmp_path):
    seen = {}

    async def fake_run(mode, incident_id, **kwargs):
        seen.update(kwargs, mode=mode)
        return {"status": "cancelled"}, [], []

    monkeypatch.setattr(module, "run", fake_run)
    monkeypatch.setattr(module, "OUT_DIR", tmp_path)
    monkeypatch.setattr(module, "load_bundle", lambda *a, **k: BUNDLE)
    monkeypatch.setattr(module, "load_ground_truth", lambda *a, **k: TRUTH)
    assert module.main(["inc-test", "estimate", "--stop-after", "plan"]) == 0
    assert seen["stop_after"] == "plan" and seen["mode"] == "estimate"
    assert (tmp_path / "inc-test" / "estimate-plan" / "report.json").exists()
    assert not (tmp_path / "inc-test" / "estimate").exists()  # a full run's reports stay


def test_stop_after_takes_only_plan(module, capsys):
    with pytest.raises(SystemExit):
        module.main(["inc-01", "estimate", "--stop-after", "operators"])
    assert "invalid choice" in capsys.readouterr().err
