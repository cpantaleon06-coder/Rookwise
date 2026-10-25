"""Budget ledger: cost formula, reservations, caps, and money as Decimal.

The first two tests use the worked examples in docs/ARCHITECTURE.md ("Cost of a call")
as test vectors, with prices read from config/prices.json.
"""

import json
import random
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from rookwise.ledger import (
    CapReached,
    Caps,
    InMemoryLedger,
    ModelPrice,
    Usage,
    call_cost,
    load_prices,
)
from rookwise.money import MICRO_USD, ZERO_USD
from rookwise.schemas import LedgerEntry

TS = datetime(2026, 10, 20, 15, 2, 11, tzinfo=UTC)
D = Decimal
PRICES = load_prices()
LIGHTNING, ULTRA = "nemotron-3.5-lightning", "nemotron-3-ultra"


def _reserve(
    ledger,
    task_id="t-1",
    level="operator",
    model=LIGHTNING,
    input_tokens=10_000,
    max_output_tokens=2_000,
    run_id="r-1",
    usd_predicted=Decimal("0.001"),
):
    return ledger.reserve(
        run_id,
        level=level,
        task_id=task_id,
        model=model,
        input_tokens=input_tokens,
        max_output_tokens=max_output_tokens,
        usd_predicted=usd_predicted,
    )


def _ledger(run_usd=Decimal("1"), **levels):
    ledger = InMemoryLedger()
    ledger.open_run("r-1", Caps(run_usd=run_usd, level_usd=levels))
    return ledger


def test_director_on_ultra_costs_0_0640():
    cost = call_cost(PRICES[ULTRA], Usage(40_000, 8_000))
    assert cost.usd == D("0.064000") == cost.usd_exact


def test_twenty_lightning_operators_cost_0_0216():
    ledger = _ledger()
    for i in range(20):
        reservation = _reserve(ledger, task_id=f"t-{i}")
        ledger.charge(reservation, Usage(10_000, 2_000), ts=TS)
    report = ledger.report("r-1")
    assert len(report.entries) == 20
    assert report.spent_by_level["operator"] == D("0.021600") == report.spent_usd
    assert report.held_usd == 0


def test_null_cached_price_falls_back_to_input_price_and_says_so():
    usage = Usage(10_000, 0, cached_tokens=4_000)
    fallback = call_cost(ModelPrice(input=D("1.0"), output=D("3.0")), usage)
    assert fallback.cached_price_fallback is True
    assert fallback.usd == call_cost(ModelPrice(D("1.0"), D("3.0")), Usage(10_000, 0)).usd
    discounted = call_cost(
        ModelPrice(input=D("1.0"), output=D("3.0"), cached_input=D("0.5")), usage
    )
    assert discounted.cached_price_fallback is False
    assert discounted.usd == D("0.008000")  # (6,000 x 1.0 + 4,000 x 0.5) / 1M


def test_reasoning_tokens_are_added_only_when_clearly_not_included():
    price = ModelPrice(input=D("0"), output=D("1"))
    assert call_cost(price, Usage(0, 600, reasoning_tokens=600)).billed_output_tokens == 600
    assert call_cost(price, Usage(0, 10, reasoning_tokens=50)).billed_output_tokens == 60


def test_invalid_cached_tokens_are_rejected():
    with pytest.raises(ValueError):
        call_cost(ModelPrice(D("1"), D("1")), Usage(100, 0, cached_tokens=101))


def test_charge_records_the_entry_and_releases_the_rest_of_the_hold():
    ledger = _ledger()
    reservation = ledger.reserve(
        "r-1",
        level="operator",
        task_id="t-1",
        model=LIGHTNING,
        input_tokens=10_000,
        max_output_tokens=2_000,
        usd_predicted=D("0.0012"),
        skills=["minimal-code"],
    )
    assert ledger.report("r-1").held_usd == reservation.usd > 0
    entry = ledger.charge(reservation, Usage(9_800, 1_900), ts=TS)
    report = ledger.report("r-1")
    assert report.held_usd == 0
    assert report.spent_usd == entry.usd_real < reservation.usd
    assert entry.cached_price_fallback is True
    assert entry.skills == ["minimal-code"]
    assert entry.usd_predicted == D("0.001200")
    with pytest.raises(ValueError):
        ledger.charge(reservation, Usage(1, 1), ts=TS)


def test_charge_can_mark_the_usage_as_estimated():
    ledger = _ledger()
    real = ledger.charge(_reserve(ledger), Usage(10, 2), ts=TS)
    estimated = ledger.charge(_reserve(ledger), Usage(10, 2), ts=TS, usage_estimated=True)
    assert real.usage_estimated is False and estimated.usage_estimated is True
    assert [e.usage_estimated for e in ledger.report("r-1").entries] == [False, True]


def test_release_frees_a_hold_without_a_charge():
    ledger = _ledger()
    reservation = _reserve(ledger)
    ledger.release(reservation)
    report = ledger.report("r-1")
    assert report.held_usd == 0 and report.entries == ()
    with pytest.raises(ValueError):
        ledger.release(reservation)


def test_run_cap_stops_the_run_and_keeps_the_partial_result():
    one_call = call_cost(PRICES[LIGHTNING], Usage(10_000, 2_000)).usd
    ledger = _ledger(run_usd=one_call * D("2.5"))
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
    ledger = _ledger(operator=D("0.001"))
    with pytest.raises(CapReached) as refused:
        _reserve(ledger)
    assert refused.value.scope == "level"
    _reserve(ledger, level="manager", model="nemotron-3-super")


def test_task_cap_stops_only_that_task():
    ledger = _ledger()
    ledger.set_task_cap("r-1", "t-1", D("0.0005"))
    with pytest.raises(CapReached) as refused:
        _reserve(ledger, task_id="t-1")
    assert refused.value.scope == "task"
    _reserve(ledger, task_id="t-2")


def test_unknown_model_and_unknown_run_are_errors():
    ledger = _ledger()
    with pytest.raises(KeyError):
        _reserve(ledger, model="not-a-model")
    with pytest.raises(KeyError):
        _reserve(ledger, run_id="r-9")
    with pytest.raises(ValueError):
        ledger.open_run("r-1", Caps(run_usd=D("1")))


# -- money as Decimal -------------------------------------------------------------------


def test_a_float_never_reaches_the_ledger():
    """Every way money enters the ledger refuses a float with TypeError."""
    with pytest.raises(TypeError, match="Decimal"):
        ModelPrice(input=1.0, output=D("3"))
    with pytest.raises(TypeError, match="Decimal"):
        ModelPrice(input=D("1"), output=D("3"), cached_input=0.5)
    with pytest.raises(TypeError, match="Decimal"):
        Caps(run_usd=0.25)
    with pytest.raises(TypeError, match="Decimal"):
        Caps(run_usd=D("1"), level_usd={"operator": 0.1})
    ledger = _ledger()
    with pytest.raises(TypeError, match="Decimal"):
        ledger.set_task_cap("r-1", "t-1", 0.01)
    with pytest.raises(TypeError, match="Decimal"):
        _reserve(ledger, usd_predicted=0.001)
    with pytest.raises(TypeError, match="Decimal"):
        _reserve(ledger, usd_predicted=1)  # an int is not money either
    with pytest.raises(ValueError):
        Caps(run_usd=D("-0.01"))
    with pytest.raises(ValueError):
        Caps(run_usd=D("NaN"))
    assert ledger.report("r-1").held_usd == 0  # nothing was reserved on the way
    # The ledger's own output models refuse floats too.
    entry = ledger.charge(_reserve(ledger), Usage(10, 2), ts=TS)
    with pytest.raises(ValidationError):
        LedgerEntry.model_validate(entry.model_dump() | {"usd_real": 0.000001})


def test_everything_the_ledger_returns_is_decimal():
    ledger = _ledger(operator=D("0.5"))
    ledger.set_task_cap("r-1", "t-1", D("0.1"))
    reservation = _reserve(ledger)
    entry = ledger.charge(reservation, Usage(9_000, 1_000), ts=TS)
    report = ledger.report("r-1")
    amounts = [
        reservation.usd,
        reservation.usd_predicted,
        entry.usd_real,
        entry.usd_predicted,
        report.spent_usd,
        report.held_usd,
        *report.spent_by_level.values(),
    ]
    assert all(type(amount) is Decimal for amount in amounts)
    assert all(amount == amount.quantize(MICRO_USD) for amount in amounts)
    for price in PRICES.values():
        assert type(price.input) is Decimal and type(price.output) is Decimal
        assert price.cached_input is None or type(price.cached_input) is Decimal


def test_prices_are_parsed_from_the_json_text_not_through_float(tmp_path):
    # A float keeps about 17 significant digits; this price has 21.
    text = '{"per_million_tokens": {"m": {"input": 0.123456789012345678901, "output": 2}}}'
    path = tmp_path / "prices.json"
    path.write_text(text, encoding="utf-8")
    price = load_prices(path)["m"]
    assert price.input == D("0.123456789012345678901")
    assert price.input != D(json.loads(text)["per_million_tokens"]["m"]["input"])
    assert price.output == D("2") and type(price.output) is Decimal


def test_costs_round_up_to_the_micro_usd():
    lightning = PRICES[LIGHTNING]
    # 35 x 0.06 + 21 x 0.24 = 7.14 per 1M tokens.
    small = call_cost(lightning, Usage(35, 21))
    assert small.usd_exact == D("0.00000714") and small.usd == D("0.000008")
    assert call_cost(lightning, Usage(1, 0)).usd == D("0.000001")  # 0.00000006
    assert call_cost(lightning, Usage(0, 0)).usd == ZERO_USD
    # Already whole micro-USD: unchanged.
    assert call_cost(PRICES[ULTRA], Usage(100, 0)).usd == D("0.000100")
    # The ledger charges the rounded amount, never the exact one.
    ledger = _ledger()
    entry = ledger.charge(_reserve(ledger, input_tokens=35, max_output_tokens=21), Usage(35, 21))
    assert entry.usd_real == D("0.000008")


def test_caps_round_down_and_predictions_round_to_nearest():
    caps = Caps(run_usd=D("0.0000019"), level_usd={"operator": D("0.00000999")})
    assert caps.run_usd == D("0.000001") and caps.level_usd["operator"] == D("0.000009")
    ledger = _ledger()
    ledger.set_task_cap("r-1", "t-1", D("0.0000159"))
    with pytest.raises(CapReached) as refused:
        _reserve(ledger, input_tokens=0, max_output_tokens=66)  # 66 x 0.24 = 15.84 -> 16
    assert refused.value.cap_usd == D("0.000015")
    predicted = [
        _reserve(ledger, task_id=f"p-{i}", usd_predicted=value).usd_predicted
        for i, value in enumerate([D("0.0000025"), D("0.0000035"), D("0.00000251")])
    ]
    assert predicted == [D("0.000002"), D("0.000004"), D("0.000003")]


def test_reserve_charge_release_totals_add_up_exactly():
    ledger = _ledger()
    open_holds = []
    # Ten charges of exactly USD 0.0001 each: as floats the sum would be
    # 0.0010000000000000002; here it is exact.
    for i in range(10):
        reservation = _reserve(
            ledger, task_id=f"a-{i}", model=ULTRA, input_tokens=100, max_output_tokens=50
        )
        open_holds.append(reservation)
        assert ledger.report("r-1").held_usd == sum((r.usd for r in open_holds), ZERO_USD)
        ledger.charge(reservation, Usage(100, 0), ts=TS)
        open_holds.remove(reservation)
    assert ledger.report("r-1").spent_usd == D("0.001000")
    # A mix: charge less than reserved, charge exactly the reservation, release.
    rng = random.Random(7)
    for i in range(60):
        tokens_in, tokens_out = rng.randint(1, 5_000), rng.randint(1, 2_000)
        reservation = _reserve(
            ledger, task_id=f"b-{i}", input_tokens=tokens_in, max_output_tokens=tokens_out
        )
        held_before = ledger.report("r-1").held_usd
        assert held_before == reservation.usd
        choice = i % 3
        if choice == 0:
            entry = ledger.charge(
                reservation, Usage(rng.randint(0, tokens_in), rng.randint(0, tokens_out))
            )
            assert entry.usd_real <= reservation.usd
        elif choice == 1:
            entry = ledger.charge(reservation, Usage(tokens_in, tokens_out))
            assert entry.usd_real == reservation.usd  # the full reservation, to the micro-USD
        else:
            ledger.release(reservation)
        assert ledger.report("r-1").held_usd == 0
    report = ledger.report("r-1")
    assert report.spent_usd == sum((e.usd_real for e in report.entries), ZERO_USD)
    assert report.spent_usd == sum(report.spent_by_level.values(), ZERO_USD)
    as_micro = sum(int(e.usd_real / MICRO_USD) for e in report.entries)
    assert report.spent_usd == as_micro * MICRO_USD


def test_rounding_never_lets_spend_pass_a_cap():
    # 35 in / 21 out on Lightning costs exactly USD 0.00000714. Rounded down, two calls
    # would record 0.000014 and fit a 0.000014 cap while really costing 0.00001428.
    ledger = _ledger(run_usd=D("0.000014"))
    ledger.charge(_reserve(ledger, input_tokens=35, max_output_tokens=21), Usage(35, 21))
    with pytest.raises(CapReached):
        _reserve(ledger, task_id="t-2", input_tokens=35, max_output_tokens=21)
    assert ledger.report("r-1").spent_usd == D("0.000008")


def test_rounding_never_lets_spend_pass_a_cap_over_random_runs():
    rng = random.Random(20261017)
    models = sorted(PRICES)
    for trial in range(200):
        cap = D(rng.randint(1, 5_000_000)).scaleb(-8)  # up to 8 decimals, so floors matter
        ledger = InMemoryLedger()
        ledger.open_run("r", Caps(run_usd=cap))
        exact_spent = ZERO_USD
        for call in range(1_000):
            model = rng.choice(models)
            tokens_in, tokens_out = rng.randint(0, 3_000), rng.randint(0, 800)
            try:
                reservation = ledger.reserve(
                    "r",
                    level="operator",
                    task_id=f"t-{call}",
                    model=model,
                    input_tokens=tokens_in,
                    max_output_tokens=tokens_out,
                    usd_predicted=ZERO_USD,
                )
            except CapReached:
                break
            usage = Usage(rng.randint(0, tokens_in), rng.randint(0, tokens_out))
            ledger.charge(reservation, usage)
            exact_spent += call_cost(PRICES[model], usage).usd_exact
        report = ledger.report("r")
        assert report.held_usd == 0, trial
        assert exact_spent <= report.spent_usd <= cap, trial


def test_a_prediction_from_expected_usage_and_the_run_totals_per_model():
    ledger = _ledger()
    expected = Usage(1_000, 500)
    common = {"level": "operator", "input_tokens": 10_000, "max_output_tokens": 2_000}
    priced = ledger.reserve(
        "r-1",
        task_id="t-1",
        model=LIGHTNING,
        usd_predicted=ZERO_USD,
        predicted_usage=expected,
        **common,
    )
    # 1,000 x 0.06 + 500 x 0.24 per 1M = USD 0.00018, rounded half-even to micro-USD.
    assert priced.usd_predicted == D("0.000180")
    given = ledger.reserve(
        "r-1",
        task_id="t-2",
        model=ULTRA,
        usd_predicted=D("0.002"),
        predicted_usage=expected,  # a caller's own prediction wins
        **common,
    )
    assert given.usd_predicted == D("0.002000")
    ledger.charge(priced, Usage(1_200, 400), TS)
    ledger.charge(given, Usage(900, 300), TS)
    report = ledger.report("r-1")
    assert report.predicted_usd == D("0.002180")
    assert [e.usd_predicted for e in report.entries] == [D("0.000180"), D("0.002000")]
    light, ultra = report.by_model[LIGHTNING], report.by_model[ULTRA]
    assert (light.calls, light.input_tokens, light.output_tokens) == (1, 1_200, 400)
    assert light.usd_predicted == D("0.000180")
    assert light.usd_real == call_cost(PRICES[LIGHTNING], Usage(1_200, 400)).usd
    assert ultra.usd_predicted == D("0.002000")
    assert sum(m.usd_real for m in report.by_model.values()) == report.spent_usd
    assert all(type(m.usd_predicted) is Decimal for m in report.by_model.values())


def test_no_expected_usage_and_no_prediction_records_zero():
    ledger = _ledger()
    reservation = _reserve(ledger, usd_predicted=ZERO_USD)
    assert reservation.usd_predicted == ZERO_USD


def test_a_free_charge_records_the_tokens_at_zero_usd():
    book = InMemoryLedger()
    book.open_run("r-free", Caps(run_usd=Decimal("1")))
    held = book.reserve(
        "r-free",
        level="operator",
        task_id="t-1",
        model="nemotron-3-ultra",
        input_tokens=1000,
        max_output_tokens=500,
        usd_predicted=Decimal("0"),
    )
    entry = book.charge(held, Usage(900, 400), free=True)
    assert (entry.input_tokens, entry.output_tokens, entry.usd_real) == (900, 400, Decimal("0"))
    report = book.report("r-free")
    assert report.spent_usd == 0 and report.held_usd == 0
    assert report.by_model["nemotron-3-ultra"].output_tokens == 400
