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
