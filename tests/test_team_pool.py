"""Pooled operator budgets: the operators of a block reserve from one ledger pool, one
reservation at a time, under a per-task limit counted as money spent. Stub transport and
a synthetic bundle; no network."""

import json
from decimal import Decimal

from harness_support import text_reply
from team_stub import (
    RUN_ID,
    TeamHandler,
    assert_budget_tree,
    assert_contract_order,
    diagnosis_reply,
    findings_payload,
    judgment_reply,
    plan_reply,
    run_stub_team,
    skills_config,
    summary_reply,
)

from rookwise.evidence import EvidenceBundle
from rookwise.ledger import InMemoryLedger
from rookwise.slicing import SlicingConfig, slice_bundle
from rookwise.team import BudgetPolicy
from rookwise.team.config import load_budget_policy

# SYNTHETIC: 55 lines, one slice each at this slice size.
LINES = [
    f"2026-03-04T04:{n // 60:02d}:{n % 60:02d}Z INFO step={n:03d} " + "x" * 60 for n in range(55)
]
BUNDLE = EvidenceBundle(sources={"app.log": "\n".join(LINES) + "\n"})
SLICING = SlicingConfig(max_slice_tokens=100, overlap_lines=0, chars_per_token=2.7, headroom=0.1)
CLAIM = {
    "claim_id": "d1",
    "text": "[stub] The first step.",
    "citations": [{"source_id": "app.log", "line_start": 1, "line_end": 1, "quote": LINES[0]}],
}
CONFIG = skills_config(manager_max_tokens=256)


class _HeldSpy(InMemoryLedger):
    """Records what the run holds right after every reservation."""

    def __init__(self):
        super().__init__()
        self.held = []

    def reserve(self, run_id, **kwargs):
        reservation = super().reserve(run_id, **kwargs)
        self.held.append((kwargs["level"], self.report(run_id).held_usd, reservation.usd))
        return reservation


def _plan():
    task = {"role": "stub-operator", "source_id": "app.log", "instruction": "[stub] Read it."}
    return plan_reply({"goal": "[stub] Read the log.", "tasks": [task]})


def _run(operator, run_usd, policy=None, ledger=None, auditor=True, config=CONFIG):
    handler = TeamHandler(
        director=[_plan()],
        diagnosis=[diagnosis_reply(CLAIM)],
        operator=operator,
        manager=[summary_reply()],
        auditor=[judgment_reply()] if auditor else [],
    )
    team, book = run_stub_team(
        handler,
        run_usd=run_usd,
        bundle=BUNDLE,
        slicing=SLICING,
        config=config,
        policy=policy,
        ledger=ledger,
    )
    return team, book, handler


def test_the_policy_is_config_and_matches_the_defaults():
    assert load_budget_policy() == BudgetPolicy()
    assert len(slice_bundle(BUNDLE.sources, SLICING).slices) == 55


def test_55_sequential_operators_run_under_usd_0_10_when_their_cost_fits():
    ledger = _HeldSpy()
    replies = [text_reply(findings_payload(), completion=20) for _ in range(55)]
    # The operators' real output ceiling (4096), so a reservation is realistic.
    real = skills_config(manager_max_tokens=256, operator_max_tokens=4096)
    team, book, handler = _run(replies, "0.10", ledger=ledger, config=real)
    tasks = [t for b in team.blocks for t in b.tasks]
    assert len(tasks) == 55 and all(t.status == "ok" for t in tasks)
    assert handler.calls["operator"] == 55 and team.unread_slices == []
    report = book.report(RUN_ID)
    assert report.spent_usd <= Decimal("0.10") and report.stops == ()
    # One reservation at a time: while an operator call is held, nothing else is.
    operator_holds = [(held, usd) for level, held, usd in ledger.held if level == "operator"]
    assert len(operator_holds) == 55 and all(held == usd for held, usd in operator_holds)
    # The old even split would have given each task (pool / 55), less than one reservation.
    pool = next(a for a in report.allocations if a.id == "pool:b-1")
    assert pool.usd / 55 < max(usd for _, usd in operator_holds)
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_refusals_still_happen_when_the_pool_is_really_exhausted():
    # Each call really costs about one reservation, so the pool runs out part way.
    replies = [text_reply(findings_payload(), prompt=2500, completion=256) for _ in range(55)]
    team, book, handler = _run(replies, "0.02")
    tasks = [t for b in team.blocks for t in b.tasks]
    ok = [t for t in tasks if t.status == "ok"]
    assert 0 < len(ok) < 55 and handler.calls["operator"] == len(ok)
    report = book.report(RUN_ID)
    assert report.spent_usd <= Decimal("0.02")  # the run cap is never passed
    assert ("budget", "pool:b-1") in [(s.scope, s.key) for s in report.stops]
    assert team.unread_slices  # the rest is reported as unread
    assert_budget_tree(book)


def test_a_runaway_task_stops_at_its_limit_and_the_pool_keeps_the_rest():
    # t-1 keeps failing validation with replies that cost more than one reservation each;
    # with a limit of three reservations its second repair no longer fits.
    bad = text_reply(json.dumps({"status": "ok", "output": {}}), prompt=4000, completion=256)
    good = [text_reply(findings_payload(), completion=20) for _ in range(54)]
    policy = BudgetPolicy(task_limit_next_rung_reservations=0)  # a limit of 3 first-rung
    team, book, handler = _run([bad, bad, *good], "0.10", policy=policy)
    first, *rest = [t for b in team.blocks for t in b.tasks]
    assert first.status == "failed" and all(t.status == "ok" for t in rest)
    report = book.report(RUN_ID)
    assert ("task", "t-1") in [(s.scope, s.key) for s in report.stops]
    assert ("budget", "pool:b-1") not in [(s.scope, s.key) for s in report.stops]
    charged = [e for e in report.entries if e.task_id == "t-1"]
    assert len(charged) == 2  # the first attempt and one repair, then the limit
    limit = team.first_reservations["t-1"] * 3
    assert sum(e.usd_real for e in charged) <= limit + charged[-1].usd_real
    assert any("ran out of its budget" in note for note in team.notes)
    assert report.spent_usd <= Decimal("0.10")
    assert_budget_tree(book)
