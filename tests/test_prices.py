"""Checks that config/prices.json has the keys the ledger and the smoke test rely on."""

import json
from numbers import Real
from pathlib import Path

PRICES_PATH = Path(__file__).resolve().parents[1] / "config" / "prices.json"


def _load() -> dict:
    return json.loads(PRICES_PATH.read_text(encoding="utf-8"))


def _is_price(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and value >= 0


def test_top_level_keys():
    data = _load()
    assert data["currency"] == "USD"
    assert isinstance(data["per_million_tokens"], dict) and data["per_million_tokens"]
    assert isinstance(data["model_ids"], dict)


def test_every_model_has_input_cached_input_and_output_prices():
    for alias, price in _load()["per_million_tokens"].items():
        assert set(price) == {"input", "cached_input", "output"}, alias
        assert _is_price(price["input"]), alias
        assert _is_price(price["output"]), alias
        assert price["cached_input"] is None or _is_price(price["cached_input"]), alias


def test_model_ids_cover_exactly_the_priced_models():
    data = _load()
    ids = {k: v for k, v in data["model_ids"].items() if not k.startswith("_")}
    assert set(ids) == set(data["per_million_tokens"])
    assert all(isinstance(v, str) for v in ids.values())
