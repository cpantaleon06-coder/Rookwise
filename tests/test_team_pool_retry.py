"""A block's pool covers its costliest task's first call plus one retry with history, so a
one-slice block can repair. The deploy.diff numbers come from the first full inc-01 record
run (2026-10-21), where that pool held the first reservation only. No network."""

import dataclasses
import json
from decimal import Decimal

from harness_support import text_reply
from team_stub import (
    GOOD_CLAIM,
    RUN_ID,
    TeamHandler,
    block,
    findings_payload,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.evidence import EvidenceBundle
from rookwise.harness import load_config
from rookwise.harness.request import ChatRequest, build_request
from rookwise.ledger import InMemoryLedger
from rookwise.slicing import SlicingConfig, slice_bundle
from rookwise.team import BudgetPolicy
from rookwise.team.config import load_budget_policy
from rookwise.team.flow import retry_request

LIGHTNING = "nemotron-3.5-lightning"
# The run's numbers for t-2 (deploy.diff, Lightning, output ceiling 4096), at the ratio the
# run used (2.7 characters per token).
FIRST_TOKENS, FIRST_CHARGE, REPAIR_TOKENS = 2524, Decimal("0.000147"), 3107
RUN_CONFIG = dataclasses.replace(load_config(env={}), chars_per_token=2.7)
_EMPTY = len(json.dumps({"messages": [{"role": "user", "content": ""}], "response_format": None}))


def _first_request():
    """A Lightning request whose input estimate at the run's ratio is the 2524 of t-2."""
    for size in range(5000, 7000):
        request = ChatRequest(
            model=LIGHTNING,
            messages=[{"role": "user", "content": "x" * (size - _EMPTY)}],
            run_id="r",
            level="operator",
            task_id="t-2",
            max_tokens=4096,
        )
        built = build_request(request, RUN_CONFIG)
        if built.input_tokens_estimate == FIRST_TOKENS:
            return built
    raise AssertionError("no request size gives the run's estimate")


def test_with_the_deploy_diff_numbers_the_pool_now_covers_the_repair():
    book = InMemoryLedger()
    first = _first_request()
    first_reservation = book.reservation_usd(LIGHTNING, FIRST_TOKENS, 4096)
    repair = book.reservation_usd(LIGHTNING, REPAIR_TOKENS, 4096)
    assert (first_reservation, repair) == (Decimal("0.001135"), Decimal("0.001170"))
    # The run: the pool was the first reservation, so the repair did not fit.
    assert first_reservation - FIRST_CHARGE == Decimal("0.000988") < repair
    # Now: a one-slice block's pool is its first reservation plus one retry's.
    retry = retry_request(first, BudgetPolicy(), RUN_CONFIG)
    assert retry.input_tokens_estimate > REPAIR_TOKENS  # the sizing is the worst case
    pool = first_reservation + book.reservation_usd(LIGHTNING, retry.input_tokens_estimate, 4096)
    assert pool - FIRST_CHARGE >= repair
    assert pool - first_reservation >= repair  # even if the first call cost its whole reservation


def test_the_retry_request_holds_the_reply_and_the_feedback():
    first = _first_request()
    policy = BudgetPolicy()
    retry = retry_request(first, policy, RUN_CONFIG)
    roles = [m["role"] for m in retry.request.messages]
    assert roles == ["user", "assistant", "user"] and retry.max_tokens == 4096
    assert len(retry.request.messages[1]["content"]) == 16_466  # 4096 x 4.02, rounded up
    assert len(retry.request.messages[2]["content"]) == policy.retry_feedback_chars == 1200


# SYNTHETIC: a one-line source for the one-slice block and a long log for a larger block
# that runs after it and takes the rest, so the small block gets exactly its need.
BIG = "".join(f"2026-03-04T03:{n:02d}:00Z INFO step={n:02d} " + "y" * 60 + "\n" for n in range(12))
BUNDLE = EvidenceBundle(
    sources={"src-a": "Sample record one: the widget weighs 12 units.\n", "big.log": BIG}
)
SLICING = SlicingConfig(max_slice_tokens=120, overlap_lines=0, chars_per_token=2.03, headroom=0.1)
BIG_SLICES = sum(s.source_id == "big.log" for s in slice_bundle(BUNDLE.sources, SLICING).slices)


def _one_slice_team(policy):
    wrong = {**GOOD_CLAIM["citations"][0], "quote": "the widget weighs 13 units."}
    handler = TeamHandler(
        director=[plan_reply(block(1), block(1, source_id="big.log"))],
        operator=[
            text_reply(findings_payload({**GOOD_CLAIM, "citations": [wrong]})),
            findings_reply(GOOD_CLAIM),  # the repair, if the pool lets it run
            *[findings_reply() for _ in range(BIG_SLICES + 1)],
        ],
        manager=[summary_reply(), summary_reply()],
        auditor=[judgment_reply()],
    )
    team, book = run_stub_team(
        handler, run_usd="0.5", policy=policy, bundle=BUNDLE, slicing=SLICING
    )
    small = next(b for b in team.blocks if b.tasks[0].slice.source_id == "src-a")
    return team, book, handler, small


def test_a_one_slice_block_repairs_inside_its_pool():
    assert BIG_SLICES >= 2
    team, book, handler, small = _one_slice_team(BudgetPolicy())
    (task,) = small.tasks
    assert task.status == "ok" and len(task.assignments) == 1  # repaired, not reassigned
    nodes = {a.id: a for a in book.report(RUN_ID).allocations}
    pool = nodes[f"pool:{small.block_id}"].usd
    assert pool >= team.first_reservations["t-1"] + team.retry_reservations["t-1"]
    assert not any(s.key == f"pool:{small.block_id}" for s in book.report(RUN_ID).stops)


def test_without_the_retry_the_pool_refuses_the_repair_as_in_the_run():
    team, book, handler, small = _one_slice_team(BudgetPolicy(pool_covers_one_retry=False))
    (task,) = small.tasks
    assert task.status == "failed" and team.retry_reservations["t-1"] == 0
    stops = {(s.scope, s.key) for s in book.report(RUN_ID).stops}
    assert ("budget", f"pool:{small.block_id}") in stops


def test_the_retry_settings_are_config():
    policy = load_budget_policy()
    assert policy == BudgetPolicy()
    assert (policy.pool_covers_one_retry, policy.retry_reply_chars_per_token) == (
        True,
        Decimal("4.02"),
    )
    assert policy.retry_feedback_chars == 1200
