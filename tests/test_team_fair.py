"""Block pools by max-min fairness, smallest need first, with unspent money rolled
forward to the later blocks. Stub transport and a synthetic bundle; no network."""

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
from rookwise.slicing import SlicingConfig, slice_bundle
from rookwise.team.flow import _fair_share

# SYNTHETIC: one line per slice at this slice size; a long log and two short sources.
LOG = [
    f"2026-03-04T05:{n // 60:02d}:{n % 60:02d}Z INFO step={n:03d} " + "x" * 60 for n in range(150)
]
SMALL = [f"2026-03-04T06:00:0{n}Z INFO note={n} " + "y" * 60 for n in range(2)]
BUNDLE = EvidenceBundle(
    sources={
        "app.log": "\n".join(LOG) + "\n",
        "metrics.csv": "\n".join(SMALL) + "\n",
        "ticket.md": "\n".join(SMALL[::-1]) + "\n",
    }
)
SLICING = SlicingConfig(max_slice_tokens=100, overlap_lines=0, chars_per_token=2.7, headroom=0.1)
CLAIM = {
    "claim_id": "d1",
    "text": "[stub] The first step.",
    "citations": [{"source_id": "app.log", "line_start": 1, "line_end": 1, "quote": LOG[0]}],
}
# Real operator and manager ceilings, so reservations are realistic.
CONFIG = skills_config(manager_max_tokens=2048, operator_max_tokens=4096)


def _task(source_id):
    return {"role": "stub-operator", "source_id": source_id, "instruction": "[stub] Read it."}


def _plan():
    return plan_reply(
        {"goal": "[stub] The log.", "tasks": [_task("app.log")]},
        {"goal": "[stub] The metrics.", "tasks": [_task("metrics.csv")]},
        {"goal": "[stub] The ticket.", "tasks": [_task("ticket.md")]},
    )


def _run(run_usd, completion):
    replies = [
        text_reply(findings_payload(), prompt=1000, completion=completion) for _ in range(154)
    ]
    handler = TeamHandler(
        director=[_plan()],
        diagnosis=[diagnosis_reply(CLAIM)],
        operator=replies,
        manager=[summary_reply() for _ in range(3)],
        auditor=[judgment_reply()],
    )
    return run_stub_team(handler, run_usd=run_usd, bundle=BUNDLE, slicing=SLICING, config=CONFIG)


def test_fair_share_takes_the_smaller_of_the_need_and_an_equal_part():
    assert _fair_share(Decimal("0.09"), Decimal("0.01"), 3) == Decimal("0.010000")
    assert _fair_share(Decimal("0.09"), Decimal("0.05"), 3) == Decimal("0.030000")
    assert _fair_share(Decimal("0.09"), Decimal("0.05"), 1) == Decimal("0.090000")  # the rest


def test_at_usd_0_10_the_small_blocks_are_read_in_full_and_the_log_gets_the_rest():
    assert len(slice_bundle(BUNDLE.sources, SLICING).slices) == 154
    team, book = _run("0.10", completion=1000)
    log, metrics, ticket = team.blocks  # plan order
    assert all(t.status == "ok" for t in metrics.tasks + ticket.tasks)  # read in full
    assert [u.source_id for u in team.unread_slices] == ["app.log"]  # only the log is short
    read = sum(t.status == "ok" for t in log.tasks)
    assert 0 < read < 150
    report = book.report(RUN_ID)
    stops = {(s.scope, s.key) for s in report.stops}
    assert ("budget", "pool:b-1") in stops and ("budget", "pool:b-2") not in stops
    # The two small blocks ran first, then the log block took what was left.
    allocated = [
        p.agent_id
        for p in (e.payload for e in team.events if e.type == "budget_allocation")
        if p.action == "allocated" and p.parent_agent_id == "a-director"
    ]
    assert allocated[1:] == ["a-manager-b-2", "a-manager-b-3", "a-manager-b-1"]
    assert report.spent_usd <= Decimal("0.10")  # the cap is never passed
    assert_budget_tree(book)


def test_money_an_early_block_leaves_reaches_a_later_block():
    team, book = _run("0.50", completion=100)  # every call costs less than expected
    report = book.report(RUN_ID)
    nodes = {a.id: a for a in report.allocations}
    plan = report.entries[0].usd_real
    free = Decimal("0.50") - plan
    auditor = nodes["budget:auditor"].usd
    director = (free * Decimal("0.20")).quantize(Decimal("0.000001"), "ROUND_FLOOR")
    early = [nodes["budget:b-2"], nodes["budget:b-3"]]
    assert all(node.released_usd > 0 for node in early)  # they left money unspent
    # The last block gets everything left at its turn: what the early blocks did not
    # spend came back to the run and is part of it.
    spent_early = sum(node.spent_usd for node in early)
    assert nodes["budget:b-1"].usd == free - auditor - director - spent_early
    assert all(t.status == "ok" for b in team.blocks for t in b.tasks)
    assert report.spent_usd <= Decimal("0.50")
    assert_contract_order(team, book)
    assert_budget_tree(book)


def test_the_cap_is_never_passed_when_money_is_short():
    for cap in ("0.02", "0.04", "0.07"):
        team, book = _run(cap, completion=2500)
        report = book.report(RUN_ID)
        assert report.spent_usd <= Decimal(cap), cap
        # Blocks run one after another and reuse what earlier ones left, so the cap
        # bounds the money spent through the allocations, not their amounts added up.
        top = sum(a.spent_usd for a in report.allocations if a.parent is None)
        assert top <= Decimal(cap), cap
        assert_budget_tree(book)
