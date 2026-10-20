"""Managers and the director receive only findings with claims, plus counts; a large
manager input is consolidated in batches; the estimate stub's --empty-slices option.
Stub transport and synthetic data only; no network."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from team_stub import (
    GOOD_CLAIM,
    RUN_ID,
    TeamHandler,
    block,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.store import InMemoryStore
from rookwise.team import BudgetPolicy

ROOT = Path(__file__).resolve().parents[1]


def _user(handler, prefix):
    return [
        b["messages"][-1]["content"]
        for b in handler.bodies
        if b["messages"][0]["content"].startswith(prefix)
    ]


def test_only_findings_with_claims_are_forwarded_and_the_rest_counted():
    store = InMemoryStore()
    handler = TeamHandler(
        director=[plan_reply(block(3))],
        operator=[findings_reply(GOOD_CLAIM), findings_reply(), findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, _ = run_stub_team(handler, run_usd="0.5", store=store)
    (outcome,) = team.blocks
    assert (outcome.slices_read, outcome.empty_slices, outcome.not_done) == (3, 1, 0)
    assert outcome.batches == 1
    (manager,) = _user(handler, "You are a manager")
    assert "Slices read: 3, of which 1 with no claims; not done: 0." in manager
    assert f"[store://{RUN_ID}/results/t-1]" in manager
    assert f"[store://{RUN_ID}/results/t-3]" in manager
    assert f"store://{RUN_ID}/results/t-2" not in manager  # claim-free: only counted
    assert "[stub] Findings." not in manager  # claims with citations, not the summaries
    assert '"quote": "the widget weighs 12 units."' in manager
    assert store.get(f"store://{RUN_ID}/results/t-2")["claims"] == []  # but stored
    (director,) = _user(handler, "You are the director of a team of AI agents, and")
    assert "Slices read: 3, of which 1 with no claims; not done: 0." in director
    assert f"store://{RUN_ID}/results/t-2" not in director
    assert f"[store://{RUN_ID}/results/t-3]" in director


def test_a_large_manager_input_is_consolidated_in_batches():
    handler = TeamHandler(
        director=[plan_reply(block(3))],
        operator=[findings_reply(GOOD_CLAIM) for _ in range(3)],
        manager=[summary_reply() for _ in range(3)],
        auditor=[judgment_reply()],
    )
    # Too small for two findings at once: each finding gets a batch of its own.
    policy = BudgetPolicy(manager_max_input_tokens=1)
    team, book = run_stub_team(handler, run_usd="0.5", policy=policy)
    (outcome,) = team.blocks
    assert outcome.batches == 3 and handler.calls["manager"] == 3
    ids = [e.task_id for e in book.report(RUN_ID).entries if e.level == "manager"]
    assert ids == ["b-1-summary-1", "b-1-summary-2", "b-1-summary-3"]
    requests = _user(handler, "You are a manager")
    assert all(f"Batch {n} of 3" in r for n, r in zip((1, 2, 3), requests, strict=True))
    assert outcome.summary.count("[stub] The block is done.") == 3
    assert outcome.status == "ok"


def test_one_batch_when_everything_fits():
    handler = TeamHandler(
        director=[plan_reply(block(2))],
        operator=[findings_reply(GOOD_CLAIM) for _ in range(2)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(handler, run_usd="0.5")
    assert team.blocks[0].batches == 1
    assert [e.task_id for e in book.report(RUN_ID).entries if e.level == "manager"] == [
        "b-1-summary"
    ]
    assert "Batch" not in _user(handler, "You are a manager")[0]


@pytest.fixture
def run_incident(monkeypatch):
    path = ROOT / "scripts" / "run_incident.py"
    spec = importlib.util.spec_from_file_location("run_incident", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_incident"] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "load_dotenv", lambda *a, **k: pytest.fail(".env was read"))
    return module


def test_the_empty_slices_choice_is_stable_and_about_the_fraction(run_incident):
    ids = [f"logs/app.log:{n}-{n + 9}" for n in range(1, 2001, 10)]
    chosen = [run_incident.is_empty_slice(i, 0.8) for i in ids]
    assert chosen == [run_incident.is_empty_slice(i, 0.8) for i in ids]  # deterministic
    assert 0.7 < sum(chosen) / len(chosen) < 0.9
    assert not any(run_incident.is_empty_slice(i, 0.0) for i in ids)
    assert all(run_incident.is_empty_slice(i, 1.0) for i in ids)


def test_the_estimate_option_makes_slices_claim_free(run_incident, tmp_path, monkeypatch):
    from test_run_incident import BUNDLE, TRUTH

    monkeypatch.setattr(run_incident, "RECORDED_RUN", tmp_path / "none.json")

    def estimate(fraction):
        report, _, _ = asyncio.run(
            run_incident.run(
                "estimate",
                "inc-test",
                bundle=BUNDLE,
                truth=TRUTH,
                run_usd="0.50",
                cassette=tmp_path / "x.json",
                empty_fraction=fraction,
            )
        )
        return report

    full, empty = estimate(0.0), estimate(1.0)
    assert sum(m["empty_slices"] for m in full["managers"]) == 0
    assert sum(m["empty_slices"] for m in empty["managers"]) == sum(
        m["slices_read"] for m in empty["managers"]
    )
    assert empty["stub_empty_slices_fraction"] == 1.0
    assert all(m["batches"] == 1 and m["input_tokens_estimate"] for m in full["managers"])


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["inc-01", "estimate", "--empty-slices", "1.5"], "between 0 and 1"),
        (["inc-01", "replay", "--empty-slices", "0.5"], "estimate mode only"),
    ],
)
def test_the_cli_checks_the_option(run_incident, monkeypatch, capsys, argv, message):
    monkeypatch.setattr(run_incident, "load_bundle", lambda *a, **k: pytest.fail("a run started"))
    assert run_incident.main(argv) == 2
    assert message in capsys.readouterr().out
