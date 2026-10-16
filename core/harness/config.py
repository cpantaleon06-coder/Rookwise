"""Harness settings from config/harness.json, config/prices.json and config/rate_limits.json.

`load_config()` returns a frozen `HarnessConfig`. Nothing is cached at module level, so
several harnesses with different settings can live in one process. Environment
variables override three settings: `HARNESS_MODE` (live, record or replay),
`HARNESS_CASSETTE_DIR` and `NEBIUS_BASE_URL`. API keys are not part of the config.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"

Mode = Literal["live", "record", "replay"]
MissingUsagePolicy = Literal["charge_full_reservation", "estimate_from_text"]


class ConfigError(ValueError):
    """The harness config is invalid or inconsistent with prices or rate limits."""


@dataclass(frozen=True)
class ModelConfig:
    alias: str
    model_id: str
    max_tokens: int
    reasoning: bool
    temperature: float | None
    top_p: float | None
    reasoning_fields: tuple[str, ...]
    disallowed: Mapping[str, tuple[Any, ...]]


@dataclass(frozen=True)
class ModelLimit:
    requests_per_minute: int
    tokens_per_minute: int


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int
    base_delay_s: float
    max_delay_s: float
    jitter: float
    max_retry_after_s: float


@dataclass(frozen=True)
class HarnessConfig:
    base_url: str
    models: Mapping[str, ModelConfig]
    limits: Mapping[str, ModelLimit]
    on_missing_usage: MissingUsagePolicy
    chars_per_token: float
    margin_tokens: int
    connect_timeout_s: float
    read_timeout_s: float
    retry: RetryConfig
    max_concurrent_requests: int
    mode: Mode
    cassette_dir: Path

    def model(self, alias: str) -> ModelConfig:
        try:
            return self.models[alias]
        except KeyError:
            raise ConfigError(f"model {alias} is not in config/harness.json") from None


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _choice(value: str, allowed: tuple[str, ...], name: str) -> str:
    if value not in allowed:
        raise ConfigError(f"{name} must be one of {allowed}, got {value!r}")
    return value


def load_config(
    harness_path: Path = CONFIG_DIR / "harness.json",
    prices_path: Path = CONFIG_DIR / "prices.json",
    rate_limits_path: Path = CONFIG_DIR / "rate_limits.json",
    env: Mapping[str, str] | None = None,
) -> HarnessConfig:
    env = os.environ if env is None else env
    data = _load(harness_path)
    model_ids = {k: v for k, v in _load(prices_path)["model_ids"].items() if not k.startswith("_")}
    per_model_limits = _load(rate_limits_path)["per_model"]

    models: dict[str, ModelConfig] = {}
    for alias, raw in data["models"].items():
        if alias not in model_ids:
            raise ConfigError(f"model {alias} has no id in config/prices.json")
        if alias not in per_model_limits:
            raise ConfigError(f"model {alias} has no entry in config/rate_limits.json")
        if raw["max_tokens"] <= 0:
            raise ConfigError(f"model {alias}: max_tokens must be positive")
        models[alias] = ModelConfig(
            alias=alias,
            model_id=model_ids[alias],
            max_tokens=raw["max_tokens"],
            reasoning=raw["reasoning"],
            temperature=raw.get("temperature"),
            top_p=raw.get("top_p"),
            reasoning_fields=tuple(raw["reasoning_fields"]),
            disallowed={k: tuple(v) for k, v in raw.get("disallowed", {}).items()},
        )
    limits = {
        alias: ModelLimit(v["requests_per_minute"], v["tokens_per_minute"])
        for alias, v in per_model_limits.items()
    }

    retry = data["retry"]
    estimate = data["input_estimate"]
    cassette = data["cassette"]
    mode = env.get("HARNESS_MODE") or cassette["mode"]
    cassette_dir = Path(env.get("HARNESS_CASSETTE_DIR") or cassette["dir"])
    if not cassette_dir.is_absolute():
        cassette_dir = REPO_ROOT / cassette_dir
    concurrency = data["max_concurrent_requests"]
    if concurrency < 1:
        raise ConfigError("max_concurrent_requests must be at least 1")
    if retry["max_attempts"] < 1:
        raise ConfigError("retry.max_attempts must be at least 1")
    return HarnessConfig(
        base_url=env.get("NEBIUS_BASE_URL") or data["base_url"],
        models=models,
        limits=limits,
        on_missing_usage=_choice(  # type: ignore[arg-type]
            data["on_missing_usage"], get_args(MissingUsagePolicy), "on_missing_usage"
        ),
        chars_per_token=float(estimate["chars_per_token"]),
        margin_tokens=int(estimate["margin_tokens"]),
        connect_timeout_s=float(data["timeout_s"]["connect"]),
        read_timeout_s=float(data["timeout_s"]["read"]),
        retry=RetryConfig(
            max_attempts=int(retry["max_attempts"]),
            base_delay_s=float(retry["base_delay_s"]),
            max_delay_s=float(retry["max_delay_s"]),
            jitter=float(retry["jitter"]),
            max_retry_after_s=float(retry["max_retry_after_s"]),
        ),
        max_concurrent_requests=int(concurrency),
        mode=_choice(mode, get_args(Mode), "HARNESS_MODE"),  # type: ignore[arg-type]
        cassette_dir=cassette_dir,
    )
