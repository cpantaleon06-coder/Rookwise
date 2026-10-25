"""Coverage: planned operator slices read. Below `low_coverage_threshold` the audit warns
"low coverage: X of Y slices read" first; the verdict is never changed. Stub transport;
no network."""

import dataclasses
from decimal import Decimal

import pytest
from team_stub import (
    GOOD_CLAIM,
    TeamHandler,
    assert_contract_order,
    block,
    diagnosis_reply,
    findings_reply,
    judgment_reply,
    operator,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.harness import load_config
from rookwise.team import BudgetPolicy
from rookwise.team.config import load_budget_policy
from rookwise.team.flow import Baseline


def _run(threshold="0.70", failing=0, tasks=3):
    good = [findings_reply(GOOD_CLAIM) for _ in range(tasks - failing)]
    bad = [findings_reply(status="failed") for _ in range(40)]
    handler = TeamHandler(
        director=[plan_reply(block(tasks))],
        operator=good + bad,
        manager=[summary_reply()],
        diagnosis=[diagnosis_reply()],
        auditor=[judgment_reply()],
    )
    policy = BudgetPolicy(
        drop_duplicate_plan_tasks=False, low_coverage_threshold=Decimal(threshold)
    )
    team, book = run_stub_team(handler, run_usd="0.5", policy=policy)
    return team, book


def test_the_threshold_is_config():
    assert load_budget_policy().low_coverage_threshold == Decimal("0.70")
    with pytest.raises(ValueError, match="low_coverage_threshold"):
        BudgetPolicy(low_coverage_threshold=Decimal("1.5"))


def test_a_full_run_has_full_coverage_and_no_warning():
    team, _ = _run()
    coverage = team.coverage
    assert (coverage.slices_read, coverage.slices_total, coverage.fraction) == (3, 3, 1.0)
    assert coverage.low is False
    assert "low coverage" not in (team.audit.warning or "")


def test_low_coverage_puts_the_warning_first_and_keeps_the_verdict():
    team, book = _run(failing=2)
    coverage = team.coverage
    assert (coverage.slices_read, coverage.slices_total, coverage.low) == (1, 3, True)
    assert team.audit.warning.startswith("low coverage: 1 of 3 slices read")
    # The same run with no threshold: the same verdict, without the coverage warning.
    plain, _ = _run(threshold="0", failing=2)
    assert team.audit.verdict == plain.audit.verdict
    rest = team.audit.warning.removeprefix("low coverage: 1 of 3 slices read")
    assert rest in ("", ".", f". {plain.audit.warning}")
    # The warning goes out in the audit_result event too.
    (event,) = [e for e in team.events if e.type == "audit_result"]
    assert event.payload.audit.warning == team.audit.warning
    assert_contract_order(team, book)


def test_coverage_at_the_threshold_is_not_low():
    team, _ = _run(threshold=str(Decimal(2) / Decimal(3)), failing=1)
    assert (team.coverage.slices_read, team.coverage.slices_total) == (2, 3)
    assert team.coverage.low is False


def test_a_baseline_reports_coverage_too():
    handler = TeamHandler(operator=[findings_reply(GOOD_CLAIM)], diagnosis=[diagnosis_reply()])
    config = load_config(env={})
    no_ladder = dataclasses.replace(
        config, escalation=dataclasses.replace(config.escalation, next={})
    )
    team, _ = run_stub_team(
        handler,
        run_usd="1.0",
        catalog=[operator("stub-baseline", "0.001", model="nemotron-3.5-lightning")],
        harness_config=no_ladder,
        policy=BudgetPolicy(max_reassignments=0, task_limit_next_rung_reservations=0),
        baseline=Baseline(
            model="nemotron-3.5-lightning", instruction="[stub]", default_role="stub-operator"
        ),
    )
    assert (team.coverage.slices_read, team.coverage.slices_total) == (1, 1)


def test_a_plan_only_run_has_no_coverage():
    handler = TeamHandler(director=[plan_reply(block(1))])
    team, _ = run_stub_team(handler, run_usd="0.5", stop_after="plan")
    assert team.coverage is None
