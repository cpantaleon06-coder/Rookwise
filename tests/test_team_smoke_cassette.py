"""The --cassette option of scripts/team_smoke.py: record to a chosen file (replacing it on
the first write) and replay from it. Stub transport only, no network."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE_KEY = "fake-key-for-cassette-tests"


def _script():
    spec = importlib.util.spec_from_file_location("team_smoke", ROOT / "scripts" / "team_smoke.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["team_smoke"] = module
    spec.loader.exec_module(module)
    # The CLI tests must never read .env.
    module.load_dotenv = lambda *a, **k: (_ for _ in ()).throw(AssertionError(".env read"))
    return module


def test_the_default_cassette_is_unchanged():
    module = _script()
    assert module.CASSETTE == ROOT / "runs" / "cassettes" / "team_smoke.json"
    assert module.run.__kwdefaults__ is None  # positional defaults only
    assert module.run.__defaults__[1] == module.CASSETTE


def test_record_replaces_the_chosen_file_and_replay_reads_it(tmp_path, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", FAKE_KEY)
    module = _script()
    path = tmp_path / "nested" / "team_smoke.run2.json"
    path.parent.mkdir()
    path.write_text('{"version": 1, "interactions": [{"stale": true}]}', encoding="utf-8")
    scenario = module.load_scenario()
    report, recorded, calls = asyncio.run(
        module.run("record", scenario, "0.05", path, transport=module._stub_transport())
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert all("stale" not in item for item in data["interactions"])  # replaced, not appended
    assert len(data["interactions"]) == len(calls) == 9
    assert FAKE_KEY not in path.read_text(encoding="utf-8")
    default = module.CASSETTE
    assert not default.exists() or default.stat().st_mtime < path.stat().st_mtime

    monkeypatch.delenv("NEBIUS_API_KEY")
    replayed_report, replayed, _ = asyncio.run(module.run("replay", scenario, "0.05", path))
    assert module._normalized(replayed) == module._normalized(recorded)
    assert replayed_report["spent_usd"] == report["spent_usd"]


def test_the_cli_refuses_a_cassette_outside_record_and_replay(tmp_path, monkeypatch, capsys):
    module = _script()
    other = str(tmp_path / "x.json")
    for mode in ("estimate", "live"):
        monkeypatch.setenv("HARNESS_MODE", mode)
        monkeypatch.setattr(sys, "argv", ["team_smoke.py", mode, "--cassette", other])
        assert module.main() == 2
        assert "--cassette is for record and replay only" in capsys.readouterr().out


def test_replay_needs_the_chosen_cassette_to_exist(tmp_path, monkeypatch, capsys):
    module = _script()
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(sys, "argv", ["team_smoke.py", "replay", "--cassette", str(missing)])
    assert module.main() == 2
    assert "No cassette at" in capsys.readouterr().out
