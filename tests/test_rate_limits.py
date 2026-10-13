"""Checks that config/rate_limits.json matches the models in config/prices.json."""

import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config"


def _load(name: str) -> dict:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def test_rate_limit_models_match_prices():
    limits = _load("rate_limits.json")["per_model"]
    prices = _load("prices.json")["per_million_tokens"]
    assert set(limits) == set(prices)


def test_limits_are_positive_integers():
    for model, limit in _load("rate_limits.json")["per_model"].items():
        assert set(limit) == {"requests_per_minute", "tokens_per_minute"}, model
        for value in limit.values():
            assert isinstance(value, int) and not isinstance(value, bool) and value > 0, model
