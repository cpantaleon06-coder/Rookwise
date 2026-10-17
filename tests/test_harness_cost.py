"""Usage parsing and the cost formula, including cached and reasoning tokens."""

from decimal import Decimal as D

from harness_support import usage

from rookwise.harness.cost import (
    call_cost,
    cost_usd,
    estimate_usage_from_text,
    full_reservation_usage,
    parse_usage,
)
from rookwise.ledger import ModelPrice, Usage, load_prices


def test_parse_usage_reads_cached_and_reasoning_tokens():
    parsed = parse_usage(usage(prompt=100, completion=40, cached=30, reasoning_tokens=25))
    assert parsed == Usage(100, 40, cached_tokens=30, reasoning_tokens=25)


def test_parse_usage_tolerates_null_and_missing_details():
    lightning = {"prompt_tokens": 35, "completion_tokens": 21, "prompt_tokens_details": None}
    assert parse_usage(lightning) == Usage(35, 21)
    nano = {"prompt_tokens": 35, "completion_tokens": 21, "total_tokens": 56}
    assert parse_usage(nano) == Usage(35, 21)
    assert parse_usage(usage(prompt=10, completion=1, cached=50)).cached_tokens == 10


def test_cached_tokens_use_the_cached_price_or_fall_back():
    used = Usage(1_000_000, 0, cached_tokens=400_000)
    assert cost_usd(ModelPrice(D("1.0"), D("3.0")), used) == D("1.000000")
    assert cost_usd(ModelPrice(D("1.0"), D("3.0"), cached_input=D("0.5")), used) == D("0.8")


def test_reasoning_tokens_count_as_output():
    price = ModelPrice(D("0"), D("1"))
    assert cost_usd(price, Usage(0, 1_000_000, reasoning_tokens=900_000)) == D("1.000000")
    assert cost_usd(price, Usage(0, 100_000, reasoning_tokens=200_000)) == D("0.300000")


def test_reasoning_inside_completion_tokens_is_billed_once():
    # Ultra, reasoning on, from the streaming probe: completion_tokens 99 already holds
    # the 95 reasoning tokens (HARNESS_RESEARCH.md, "Reasoning token accounting").
    raw = usage(prompt=41, completion=99, cached=0, reasoning_tokens=95)
    price = load_prices()["nemotron-3-ultra"]
    cost = call_cost(price, parse_usage(raw))
    assert cost.billed_output_tokens == 99
    assert cost.usd == D("0.000338")  # (41 x 1.00 + 99 x 3.00) / 1M, exact


def test_full_reservation_costs_exactly_the_worst_case():
    price = load_prices()["nemotron-3-ultra"]
    assert cost_usd(price, full_reservation_usage(500, 256)) == cost_usd(price, Usage(500, 256))


def test_estimate_from_text_uses_the_running_total_as_a_floor_and_caps_at_max():
    guess = estimate_usage_from_text(100, "abcdef", "", 3, max_tokens=64)
    assert guess == Usage(100, 2)
    floor = estimate_usage_from_text(100, "ab", "", 3, max_tokens=64, running=Usage(38, 13))
    assert floor == Usage(38, 13)
    assert estimate_usage_from_text(100, "x" * 999, "", 3, max_tokens=64).output_tokens == 64
