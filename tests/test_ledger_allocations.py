"""Ledger allocations: sub-budgets held out of the run or out of a parent allocation.

Calls use Ultra input tokens only (USD 1.00 per 1M), so n tokens cost exactly n
micro-USD and every amount below is exact.
"""

import random
from decimal import ROUND_FLOOR, Decimal

import pytest

from rookwise.ledger import CapReached, Caps, InMemoryLedger, Usage
from rookwise.money import MICRO_USD, ZERO_USD

D = Decimal
ULTRA = "nemotron-3-ultra"


def _book(run_usd="1", **levels):
    book = InMemoryLedger()
    book.open_run("r", Caps(run_usd=D(run_usd), level_usd={k: D(v) for k, v in levels.items()}))
    return book


def _tokens(usd: str) -> int:
    return int(D(usd) / MICRO_USD)


def _hold(book, usd, budget_id=None, task_id="t", level="operator"):
    return book.reserve(
        "r",
        level=level,
        task_id=task_id,
        model=ULTRA,
        input_tokens=_tokens(usd),
        max_output_tokens=0,
        usd_predicted=ZERO_USD,
        budget_id=budget_id,
    )


def _spend(book, reservation, usd):
    return book.charge(reservation, Usage(_tokens(usd), 0))


def test_children_can_never_hold_more_than_their_parent():
    book = _book("1")
    manager = book.allocate("r", "m-1", D("0.6"))
    assert book.free("r") == D("0.4")
    with pytest.raises(CapReached) as refused:
        book.allocate("r", "m-2", D("0.5"))
    stop = refused.value
    assert (stop.scope, stop.key, stop.cap_usd, stop.committed_usd, stop.requested_usd) == (
        "run",
        "r",
        D("1"),
        D("0.6"),
        D("0.5"),
    )
    assert book.report("r").stops == ()  # a refused allocation stops nothing
    book.allocate("r", "m-2", D("0.4"))
    assert book.free("r") == 0
    book.allocate("r", "o-1", D("0.35"), parent=manager.id)
    with pytest.raises(CapReached) as refused:
        book.allocate("r", "o-2", D("0.3"), parent=manager.id)
    assert (refused.value.scope, refused.value.key) == ("budget", "m-1")
    book.allocate("r", "o-2", D("0.25"), parent=manager.id)
    assert book.free("r", "m-1") == 0
    report = book.report("r")
    for node in report.allocations:
        children = [a.usd for a in report.allocations if a.parent == node.id]
        assert sum(children, ZERO_USD) <= node.usd
    assert sum((a.usd for a in report.allocations if a.parent is None), ZERO_USD) <= D("1")


def test_a_call_inside_an_allocation_is_counted_once():
    book = _book("1", operator="0.45")
    book.allocate("r", "a", D("0.5"))
    _hold(book, "0.4", budget_id="a")
    assert book.free("r", "a") == D("0.1")
    assert book.free("r") == D("0.5")  # the hold sits inside the 0.5 already held for "a"
    # Level caps still count every call, inside an allocation or not: 0.4 + 0.1 > 0.45.
    with pytest.raises(CapReached) as refused:
        _hold(book, "0.1", task_id="t-2")
    assert refused.value.scope == "level"
    _hold(book, "0.5", level="manager", task_id="m")
    assert book.free("r") == 0
    with pytest.raises(CapReached) as refused:
        _hold(book, "0.000001", level="manager", task_id="m2")
    assert refused.value.scope == "run"


def test_a_call_that_does_not_fit_stops_only_its_allocation():
    book = _book("1")
    book.allocate("r", "a", D("0.1"))
    book.allocate("r", "b", D("0.1"))
    with pytest.raises(CapReached) as refused:
        _hold(book, "0.15", budget_id="a")
    assert (refused.value.scope, refused.value.key) == ("budget", "a")
    with pytest.raises(CapReached):
        _hold(book, "0.000001", budget_id="a")  # stopped from now on
    with pytest.raises(CapReached):
        book.allocate("r", "a-child", D("0.01"), parent="a")
    assert book.free("r", "a") == 0
    _spend(book, _hold(book, "0.1", budget_id="b"), "0.1")
    _spend(book, _hold(book, "0.2", task_id="root"), "0.2")
    assert book.free("r") == D("0.6")
    assert [(s.scope, s.key) for s in book.report("r").stops] == [("budget", "a")]


def test_closing_gives_the_unspent_part_back_to_the_parent():
    book = _book("1")
    manager = book.allocate("r", "m", D("0.5"))
    operator = book.allocate("r", "o", D("0.2"), parent="m")
    _spend(book, _hold(book, "0.15", budget_id="o"), "0.05")
    assert book.free("r", "o") == D("0.15")
    assert book.free("r", "m") == D("0.3")
    assert book.close(operator) == D("0.15")
    assert book.free("r", "m") == D("0.45")
    assert book.close(manager) == D("0.45")
    assert book.free("r") == D("0.95")
    report = {a.id: a for a in book.report("r").allocations}
    assert (report["o"].spent_usd, report["o"].released_usd, report["o"].closed) == (
        D("0.05"),
        D("0.15"),
        True,
    )
    assert (report["m"].spent_usd, report["m"].released_usd) == (D("0.05"), D("0.45"))
    assert report["m"].usd == report["m"].spent_usd + report["m"].released_usd


def test_close_needs_settled_calls_and_closed_children():
    book = _book("1")
    manager = book.allocate("r", "m", D("0.5"))
    operator = book.allocate("r", "o", D("0.2"), parent="m")
    held = _hold(book, "0.1", budget_id="o")
    with pytest.raises(ValueError, match="holds reservations"):
        book.close(operator)
    with pytest.raises(ValueError, match="holds reservations"):
        book.close(manager)
    book.release(held)
    with pytest.raises(ValueError, match="open child"):
        book.close(manager)
    assert book.close(operator) == D("0.2")
    with pytest.raises(ValueError, match="closed"):
        book.close(operator)
    with pytest.raises(ValueError, match="closed"):
        _hold(book, "0.01", budget_id="o")
    with pytest.raises(ValueError, match="closed"):
        book.allocate("r", "o-child", D("0.01"), parent="o")
    assert book.free("r", "o") == 0
    with pytest.raises(KeyError):
        _hold(book, "0.01", budget_id="nope")
    with pytest.raises(KeyError):
        book.free("r", "nope")
    with pytest.raises(ValueError, match="already exists"):
        book.allocate("r", "m", D("0.1"))


def test_a_charge_that_runs_over_stops_the_allocation_and_counts_upward():
    book = _book("0.12")
    book.allocate("r", "a", D("0.1"))
    reservation = _hold(book, "0.05", budget_id="a")
    _spend(book, reservation, "0.15")  # real usage above the reservation
    stops = {(s.scope, s.key) for s in book.report("r").stops}
    assert stops == {("budget", "a"), ("run", "r")}
    assert book.free("r") == 0 and book.free("r", "a") == 0


def test_allocations_refuse_floats_and_round_down():
    book = _book("1")
    with pytest.raises(TypeError, match="Decimal"):
        book.allocate("r", "a", 0.1)
    assert book.allocate("r", "a", D("0.0000019")).usd == D("0.000001")


def test_random_trees_add_up_exactly():
    rng = random.Random(42)
    for trial in range(50):
        book = _book("0.5")
        allocations = {}
        for step in range(80):
            scope = rng.choice([None, *allocations])
            free = book.free("r", scope)
            amount = (free * D(rng.randint(1, 90)) / 100).quantize(MICRO_USD, ROUND_FLOOR)
            if rng.random() < 0.4:
                allocations[f"a-{step}"] = book.allocate("r", f"a-{step}", amount, parent=scope)
            else:
                held = _hold(book, amount, scope, task_id=f"t-{step}")
                if rng.random() < 0.7:
                    _spend(
                        book, held, (held.usd * D(rng.randint(0, 100)) / 100).quantize(MICRO_USD)
                    )
                else:
                    book.release(held)
            assert book.report("r").held_usd == 0, (trial, step)
        # Children are created after their parents, so reverse order closes them first.
        released = {a.id: book.close(a) for a in reversed(list(allocations.values()))}
        report = book.report("r")
        for node in report.allocations:
            assert node.spent_usd + released[node.id] == node.usd, (trial, node.id)
            children = [a.usd for a in report.allocations if a.parent == node.id]
            assert sum(children, ZERO_USD) <= node.usd, (trial, node.id)
        assert book.free("r") + report.spent_usd == D("0.5"), trial
