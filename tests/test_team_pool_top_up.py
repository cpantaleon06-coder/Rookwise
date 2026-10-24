"""An exhausted block pool draws extra money from the run's unallocated balance
(`pool_top_up`), the shape of the third inc-01 run: a large block whose real calls cost
more than estimated runs dry while the run still has money nobody holds. Stub transport
and a synthetic bundle; no network."""

from dataclasses import replace
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

import rookwise.team.flow as flow
from rookwise.evidence import EvidenceBundle
from rookwise.slicing import SlicingConfig, slice_bundle
from rookwise.team import BudgetPolicy
from rookwise.team.config import load_budget_policy

# SYNTHETIC: one line per slice at this slice size. The log block runs first (smaller
# need); the database block runs last.
LOG = [
    f"2026-03-04T07:{n // 60:02d}:{n % 60:02d}Z INFO step={n:03d} " + "x" * 60 for n in range(20)
]
DB = [f"2026-03-04T08:{n // 60:02d}:{n % 60:02d}Z INFO row={n:03d} " + "y" * 60 for n in range(30)]
BUNDLE = EvidenceBundle(sources={"app.log": "\n".join(LOG) + "\n", "db.log": "\n".join(DB) + "\n"})
SLICING = SlicingConfig(max_slice_tokens=100, overlap_lines=0, chars_per_token=2.7, headroom=0.1)
CLAIM = {
    "claim_id": "d1",
    "text": "[stub] The first step.",
    "citations": [{"source_id": "app.log", "line_start": 1, "line_end": 1, "quote": LOG[0]}],
}
# Real operator and manager ceilings, so reservations are realistic.
CONFIG = skills_config(manager_max_tokens=2048, operator_max_tokens=4096)
# Log replies cost about twice the expected operator output; database replies are cheap.
COSTLY = 3800


def _task(source_id):
    return {"role": "stub-operator", "source_id": source_id, "instruction": "[stub] Read it."}


def _run(run_usd, policy):
    replies = [text_reply(findings_payload(), completion=COSTLY) for _ in LOG]
    replies += [text_reply(findings_payload(), completion=20) for _ in DB]
    handler = TeamHandler(
        director=[
            plan_reply(
                {"goal": "[stub] The log.", "tasks": [_task("app.log")]},
                {"goal": "[stub] The database.", "tasks": [_task("db.log")]},
            )
        ],
        diagnosis=[diagnosis_reply(CLAIM)],
        operator=replies,
        manager=[summary_reply(), summary_reply()],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(
        handler, run_usd=run_usd, bundle=BUNDLE, slicing=SLICING, config=CONFIG, policy=policy
    )
    return team, book, handler


def _allocation(book, budget_id):
    return next((a for a in book.report(RUN_ID).allocations if a.id == budget_id), None)


def _top_up_event(team):
    """The `allocated` event of the log pool's top-up: the manager's third allocation."""
    allocated = [
        e.payload
        for e in team.events
        if e.type == "budget_allocation"
        and e.payload.action == "allocated"
        and e.payload.agent_id == "a-manager-b-1"
    ]
    return allocated[2] if len(allocated) > 2 else None


def test_the_switch_and_the_limit_are_config():
    policy = load_budget_policy()
    assert policy.pool_top_up is True
    assert policy.pool_top_up_max_ratio == Decimal("1.0")
    assert len(slice_bundle(BUNDLE.sources, SLICING).slices) == 50


def test_without_the_top_up_the_large_block_runs_dry_with_run_money_left():
    team, book, handler = _run("1.00", BudgetPolicy(pool_top_up=False))
    log, db = team.blocks
    refused = [t for t in log.tasks if t.status != "ok"]
    assert refused and log.top_up_usd == 0
    assert _allocation(book, "pool:b-1:top-up") is None
    assert ("budget", "pool:b-1") in [(s.scope, s.key) for s in book.report(RUN_ID).stops]
    assert all(t.status == "ok" for t in db.tasks)
    # Money the run never used: well above what the refused tasks would have cost.
    report = book.report(RUN_ID)
    assert report.caps.run_usd - report.spent_usd > len(refused) * team.first_reservations["t-1"]


def test_an_exhausted_pool_draws_from_the_unallocated_run_money():
    off, off_book, _ = _run("1.00", BudgetPolicy(pool_top_up=False))
    team, book, handler = _run("1.00", BudgetPolicy())
    log, db = team.blocks
    assert all(t.status == "ok" for b in team.blocks for t in b.tasks)
    assert handler.calls["operator"] == len(LOG) + len(DB) and team.unread_slices == []
    pool, extra = _allocation(book, "pool:b-1"), _allocation(book, "pool:b-1:top-up")
    # One extra allocation from the run, within the per-pool limit, closed at the end of
    # the block with its rest given back to the run.
    assert extra is not None and extra.parent is None and extra.closed
    assert 0 < extra.usd <= pool.usd * BudgetPolicy().pool_top_up_max_ratio
    assert log.top_up_usd == extra.usd
    assert _allocation(book, "pool:b-2:top-up") is None  # the cheap block needed none
    assert any("tops it up" in note for note in team.notes)
    # The auditor's allocation and the director's diagnosis are untouched: the same
    # auditor allocation as without the top-up, and the diagnosis and audit ran.
    assert _allocation(book, "budget:auditor").usd == _allocation(off_book, "budget:auditor").usd
    assert team.diagnosis is not None and team.audit is not None
    report = book.report(RUN_ID)
    assert report.spent_usd <= report.caps.run_usd and report.stops == ()
    assert_contract_order(team, book)
    assert_budget_tree(book)


def _spy(monkeypatch):
    """Record each block's need and what each block's top-up must leave in the run."""
    needs, keeps = [], {}
    need, manage = flow._Team._block_need, flow._Team._manage

    def spy_need(self, items):
        needs.append(need(self, items))
        return needs[-1]

    async def spy_manage(self, block_id, *args, keep_in_run):
        keeps[block_id] = keep_in_run
        return await manage(self, block_id, *args, keep_in_run=keep_in_run)

    monkeypatch.setattr(flow._Team, "_block_need", spy_need)
    monkeypatch.setattr(flow._Team, "_manage", spy_manage)
    return needs, keeps


def _director_share(book):
    """20 % of what was free after the plan; the auditor's allocation is 25 % of it."""
    free_after_plan = _allocation(book, "budget:auditor").usd / BudgetPolicy().auditor_share
    return free_after_plan * BudgetPolicy().director_share


def test_the_top_up_leaves_the_director_share_and_the_later_needs_in_the_run(monkeypatch):
    needs, keeps = _spy(monkeypatch)
    team, book, _ = _run("1.00", BudgetPolicy())
    event = _top_up_event(team)
    assert event is not None and event.parent_agent_id == "a-director"
    # The log block runs first, so its top-up keeps the director's share and the
    # database block's need; the database block, last, keeps the director's share only.
    log_need, db_need = needs
    assert keeps["b-1"] - db_need == keeps["b-2"]
    assert abs(keeps["b-2"] - _director_share(book)) < Decimal("0.000002")
    # What the run still had free once the top-up was drawn covers what it must keep.
    assert event.parent_free_usd >= keeps["b-1"]
    assert _allocation(book, "budget:b-2").usd >= db_need


def test_the_per_pool_limit_bounds_the_top_up():
    small = BudgetPolicy(pool_top_up_max_ratio=Decimal("0.2"))
    team, book, _ = _run("1.00", small)
    pool, extra = _allocation(book, "pool:b-1"), _allocation(book, "pool:b-1:top-up")
    assert extra is not None and extra.usd <= pool.usd * Decimal("0.2")
    full, _, _ = _run("1.00", BudgetPolicy())
    off, _, _ = _run("1.00", BudgetPolicy(pool_top_up=False))
    done = [sum(t.status == "ok" for t in r.blocks[0].tasks) for r in (off, team, full)]
    assert done[0] < done[1] <= done[2] == len(LOG)
    assert_budget_tree(book)


def test_a_ratio_of_zero_turns_the_top_up_off():
    team, book, _ = _run("1.00", BudgetPolicy(pool_top_up_max_ratio=Decimal("0")))
    off, _, _ = _run("1.00", BudgetPolicy(pool_top_up=False))
    assert _allocation(book, "pool:b-1:top-up") is None
    assert [t.status for t in team.blocks[0].tasks] == [t.status for t in off.blocks[0].tasks]


def test_no_top_up_from_money_the_later_blocks_need(monkeypatch):
    # At this cap the run has money beyond the director's share while the log block runs,
    # but less than that plus the database block's need: no top-up.
    needs, keeps = _spy(monkeypatch)
    team, book, _ = _run("0.08", BudgetPolicy())
    off, off_book, _ = _run("0.08", BudgetPolicy(pool_top_up=False))
    assert _allocation(book, "pool:b-1:top-up") is None
    assert any(t.status != "ok" for t in team.blocks[0].tasks)
    report = book.report(RUN_ID)
    spent_by_b1 = _allocation(book, "budget:b-1").usd
    free_in_b1 = report.caps.run_usd - _allocation(book, "budget:auditor").usd - spent_by_b1
    assert free_in_b1 - _director_share(book) > 0  # money above the director's share
    assert free_in_b1 < keeps["b-1"]  # but not above what the database block needs
    assert [t.status for b in team.blocks for t in b.tasks] == [
        t.status for b in off.blocks for t in b.tasks
    ]
    assert book.report(RUN_ID).spent_usd == off_book.report(RUN_ID).spent_usd
    assert_budget_tree(book)


def test_the_policy_rejects_a_negative_ratio():
    try:
        replace(BudgetPolicy(), pool_top_up_max_ratio=Decimal("-0.1"))
    except ValueError as error:
        assert "pool_top_up_max_ratio" in str(error)
    else:
        raise AssertionError("a negative ratio was accepted")
