"""Budget ledger: cost formula, reservations and caps.

The first two tests use the arithmetic in docs/ARCHITECTURE.md ("Estimate of one run")
as test vectors, with prices read from config/prices.json.
"""

from datetime import UTC, datetime

import pytest

from rookwise.ledger import (
    CapReached,
    Caps,
    InMemoryLedger,
    ModelPrice,
    Usage,
    call_cost,
    load_prices,
)

TS = datetime(2026, 10, 20, 15, 2, 11, tzinfo=UTC)


def _reserve(
    ledger,
    task_id="t-1",
    level="operator",
    model="nemotron-3.5-lightning",
    input_tokens=10_000,
    max_output_tokens=2_000,
    run_id="r-1",
):
    return ledger.reserve(
        run_id,
        level=level,
        task_id=task_id,
        model=model,
        input_tokens=input_tokens,
        max_output_tokens=max_output_tokens,
        usd_predicted=0.001,
    )


def test_director_on_ultra_costs_0_0640():
    cost = call_cost(load_prices()["nemotron-3-ultra"], Usage(40_000, 8_000))
    assert round(cost.usd, 4) == 0.0640


def test_twenty_lightning_operators_cost_0_0216():
    ledger = InMemoryLedger()
    ledger.open_run("r-1", Caps(run_usd=1.0))
    for i in range(20):
        reservation = _reserve(ledger, task_id=f"t-{i}")
        ledger.charge(reservation, Usage(10_000, 2_000), ts=TS)
    report = ledger.report("r-1")
    assert len(report.entries) == 20
    assert round(report.spent_by_level["operator"], 4) == 0.0216
    assert report.held_usd == 0


def test_null_cached_price_falls_back_to_input_price_and_says_so():
    usage = Usage(10_000, 0, cached_tokens=4_000)
    fallback = call_cost(ModelPrice(input=1.0, output=3.0), usage)
    assert fallback.cached_price_fallback is True
    assert fallback.usd == call_cost(ModelPrice(1.0, 3.0), Usage(10_000, 0)).usd
    discounted = call_cost(ModelPrice(input=1.0, output=3.0, cached_input=0.5), usage)
    assert discounted.cached_price_fallback is False
    assert round(discounted.usd, 6) == round((6_000 * 1.0 + 4_000 * 0.5) / 1e6, 6)


def test_reasoning_tokens_are_added_only_when_clearly_not_included():
    price = ModelPrice(input=0.0, output=1.0)
    assert call_cost(price, Usage(0, 600, reasoning_tokens=600)).billed_output_tokens == 600
    assert call_cost(price, Usage(0, 10, reasoning_tokens=50)).billed_output_tokens == 60


def test_invalid_cached_tokens_are_rejected():
    with pytest.raises(ValueError):
        call_cost(ModelPrice(1.0, 1.0), Usage(100, 0, cached_tokens=101))


def test_charge_records_the_entry_and_releases_the_rest_of_the_hold():
    ledger = InMemoryLedger()
    ledger.open_run("r-1", Caps(run_usd=1.0))
    reservation = ledger.reserve(
        "r-1",
        level="operator",
        task_id="t-1",
        model="nemotron-3.5-lightning",
        input_tokens=10_000,
        max_output_tokens=2_000,
        usd_predicted=0.0012,
        skills=["minimal-code"],
    )
    assert ledger.report("r-1").held_usd == reservation.usd > 0
    entry = ledger.charge(reservation, Usage(9_800, 1_900), ts=TS)
    report = ledger.report("r-1")
    assert report.held_usd == 0
    assert report.spent_usd == entry.usd_real < reservation.usd
    assert entry.cached_price_fallback is True
    assert entry.skills == ["minimal-code"]
    assert entry.usd_predicted == 0.0012
    with pytest.raises(ValueError):
        ledger.charge(reservation, Usage(1, 1), ts=TS)


def test_release_frees_a_hold_without_a_charge():
    ledger = InMemoryLedger()
    ledger.open_run("r-1", Caps(run_usd=1.0))
    reservation = _reserve(ledger)
    ledger.release(reservation)
    report = ledger.report("r-1")
    assert report.held_usd == 0 and report.entries == ()
    with pytest.raises(ValueError):
        ledger.release(reservation)


def test_run_cap_stops_the_run_and_keeps_the_partial_result():
    one_call = call_cost(load_prices()["nemotron-3.5-lightning"], Usage(10_000, 2_000)).usd
    ledger = InMemoryLedger()
    ledger.open_run("r-1", Caps(run_usd=one_call * 2.5))
    for i in range(2):
        ledger.charge(_reserve(ledger, task_id=f"t-{i}"), Usage(10_000, 2_000), ts=TS)
    with pytest.raises(CapReached) as refused:
        _reserve(ledger, task_id="t-2")
    assert refused.value.scope == "run"
    # A smaller call would fit, but the run is stopped.
    with pytest.raises(CapReached):
        _reserve(ledger, task_id="t-3", input_tokens=1, max_output_tokens=1)
    report = ledger.report("r-1")
    assert len(report.entries) == 2
    assert [stop.scope for stop in report.stops] == ["run"]


def test_level_cap_stops_only_that_level():
    ledger = InMemoryLedger()
    ledger.open_run("r-1", Caps(run_usd=1.0, level_usd={"operator": 0.001}))
    with pytest.raises(CapReached) as refused:
        _reserve(ledger)
    assert refused.value.scope == "level"
    _reserve(ledger, level="manager", model="nemotron-3-super")


def test_task_cap_stops_only_that_task():
    ledger = InMemoryLedger()
    ledger.open_run("r-1", Caps(run_usd=1.0))
    ledger.set_task_cap("r-1", "t-1", 0.0005)
    with pytest.raises(CapReached) as refused:
        _reserve(ledger, task_id="t-1")
    assert refused.value.scope == "task"
    _reserve(ledger, task_id="t-2")


def test_unknown_model_and_unknown_run_are_errors():
    ledger = InMemoryLedger()
    ledger.open_run("r-1", Caps(run_usd=1.0))
    with pytest.raises(KeyError):
        _reserve(ledger, model="not-a-model")
    with pytest.raises(KeyError):
        _reserve(ledger, run_id="r-9")
    with pytest.raises(ValueError):
        ledger.open_run("r-1", Caps(run_usd=1.0))
