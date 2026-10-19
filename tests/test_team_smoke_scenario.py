"""The synthetic smoke scenario (examples/team_smoke/) and an offline run of
scripts/team_smoke.py on its stub transport. No network."""

import asyncio
import importlib.util
from decimal import Decimal
from pathlib import Path

from rookwise.runner import OperatorSpec
from rookwise.skills import load_config

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("team_smoke", ROOT / "scripts" / "team_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_scenario_is_synthetic_and_plants_a_verifiable_root_cause():
    scenario = _script().load_scenario()
    log, runbook = scenario["texts"]["app-log"], scenario["texts"]["runbook"]
    assert len(log.splitlines()) == 60 and len(runbook.splitlines()) == 20
    assert log.startswith("# SYNTHETIC") and runbook.startswith("# SYNTHETIC")
    assert Decimal(scenario["run_usd"]) == Decimal("0.25")
    rc = scenario["root_cause"]
    lines = log.splitlines()
    for number, text in zip(rc["lines"], rc["line_texts"], strict=True):
        assert text in lines[number - 1], number
    roles = load_config()["roles"]
    for entry in scenario["catalog"]:
        spec = OperatorSpec.model_validate(entry)
        assert spec.skills == roles[spec.role]["skills"]  # real roles from config/skills.json


def test_an_offline_run_of_the_scenario_stays_under_the_cap(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    module = _script()
    report, events, calls = asyncio.run(module.run("estimate", module.load_scenario()))
    assert report["status"] == "finished" and report["under_cap"]
    assert report["root_cause_found"] and report["citation_verified_rate"] == 1.0
    assert len(calls) == 8 and events[-1]["type"] == "run_finished"
    # The run summary puts the ledger's prediction next to the real cost, per model.
    assert Decimal(report["predicted_usd"]) > 0 and report["prediction_error"] is not None
    for row in report["by_model"].values():
        assert Decimal(row["usd_predicted"]) > 0 and Decimal(row["usd"]) > 0
    assert set(report["prediction_error_by_model"]) == set(report["by_model"])
    assert all(Decimal(call["usd_predicted"]) > 0 for call in calls)
    assert report["length_finishes"] == 0
    assert report["unread_slices"] == [] and report["empty_sources"] == []
    tasks = [t for block in report["blocks"] for t in block["tasks"]]
    assert {t["slice_id"] for t in tasks} == {"app-log:1-60", "runbook:1-20"}
    assert sum(sum(v.values()) for v in report["outcomes_by_role"].values()) == 8
    finished = events[-1]["payload"]
    assert finished["predicted_usd"] == report["predicted_usd"]


def test_the_cap_can_be_set_for_one_run(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    module = _script()
    report, _, _ = asyncio.run(module.run("estimate", module.load_scenario(), "0.05"))
    assert report["cap_usd"] == "0.050000" and report["under_cap"]
