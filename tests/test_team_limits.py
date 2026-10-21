"""The ladder-aware per-task limit and the startup check of slice size against the
operators' input ceiling. Stub transport; no network."""

import dataclasses
from decimal import Decimal

import pytest
from team_stub import (
    GOOD_CLAIM,
    TeamHandler,
    block,
    findings_reply,
    judgment_reply,
    plan_reply,
    run_stub_team,
    summary_reply,
)

from rookwise.harness import ConfigError, load_config
from rookwise.harness.config import EscalationConfig
from rookwise.slicing import load_slicing_config
from rookwise.team import BudgetPolicy


def _handler():
    return TeamHandler(
        director=[plan_reply(block(1))],
        operator=[findings_reply(GOOD_CLAIM)],
        manager=[summary_reply()],
        auditor=[judgment_reply()],
    )


def test_the_limit_holds_three_first_rung_and_one_next_rung_reservation():
    team, book = run_stub_team(_handler(), run_usd="0.5")
    first, limit = team.first_reservations["t-1"], team.task_limits["t-1"]
    next_rung = limit - first * 3
    # Lightning to Super costs more for the same request, so the rung up is the larger part.
    assert next_rung > first and limit == (first * 3 + next_rung)
    no_ladder = dataclasses.replace(load_config(env={}), escalation=EscalationConfig(2, {}))
    team, _ = run_stub_team(_handler(), run_usd="0.5", harness_config=no_ladder)
    assert team.task_limits["t-1"] == team.first_reservations["t-1"] * 3  # top of the ladder


def test_the_multiples_are_config_values():
    policy = BudgetPolicy(task_limit_first_rung_reservations=2, task_limit_next_rung_reservations=0)
    team, _ = run_stub_team(_handler(), run_usd="0.5", policy=policy)
    assert team.task_limits["t-1"] == (team.first_reservations["t-1"] * 2).quantize(
        Decimal("0.000001"), "ROUND_FLOOR"
    )
    with pytest.raises(ValueError, match="task_limit_first_rung_reservations"):
        BudgetPolicy(task_limit_first_rung_reservations=0)
    with pytest.raises(ValueError, match="task_limit_next_rung_reservations"):
        BudgetPolicy(task_limit_next_rung_reservations=-1)


def test_a_slice_size_the_operators_cannot_take_fails_fast_naming_both_keys():
    policy = BudgetPolicy(operator_max_input_tokens=12_500)  # the default slice is 12,000
    with pytest.raises(ConfigError) as failure:
        run_stub_team(TeamHandler(), run_usd="0.5", policy=policy)
    message = str(failure.value)
    assert "max_slice_tokens (12000, config/slicing.json)" in message
    assert "operator_max_input_tokens (12500, config/budget.json)" in message
    wide = dataclasses.replace(load_slicing_config(), max_slice_tokens=49_500)
    with pytest.raises(ConfigError, match="max_slice_tokens"):
        run_stub_team(TeamHandler(), run_usd="0.5", slicing=wide)  # default ceiling: 50,000


def test_the_check_runs_before_any_model_call():
    handler = TeamHandler()
    with pytest.raises(ConfigError):
        run_stub_team(handler, run_usd="0.5", policy=BudgetPolicy(operator_max_input_tokens=1))
    assert handler.bodies == []
