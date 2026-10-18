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
LoopProtocol = Literal["native_tools", "json_protocol"]
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
    max_tokens_cap: int
    loop_protocol: LoopProtocol


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
class LoopConfig:
    max_steps: int
    tool_timeout_s: float
    tool_result_max_tokens: int
    max_repeats: int
    max_protocol_errors: int
    json_protocol_response_format: Literal["json_object", "none"]


@dataclass(frozen=True)
class EscalationConfig:
    max_repairs: int
    next: Mapping[str, str]


@dataclass(frozen=True)
class HarnessConfig:
    base_url: str
    models: Mapping[str, ModelConfig]
    limits: Mapping[str, ModelLimit]
    on_missing_usage: MissingUsagePolicy
    chars_per_token: float
    input_headroom: float
    margin_tokens: int
    prediction_output_fraction: float
    connect_timeout_s: float
    read_timeout_s: float
    retry: RetryConfig
    max_concurrent_requests: int
    mode: Mode
    cassette_dir: Path
    loop: LoopConfig
    escalation: EscalationConfig

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
        if not 0 < raw["max_tokens"] <= raw["max_tokens_cap"]:
            raise ConfigError(f"model {alias}: need 0 < max_tokens <= max_tokens_cap")
        models[alias] = ModelConfig(
            alias=alias,
            model_id=model_ids[alias],
            max_tokens=raw["max_tokens"],
            reasoning=raw["reasoning"],
            temperature=raw.get("temperature"),
            top_p=raw.get("top_p"),
            reasoning_fields=tuple(raw["reasoning_fields"]),
            disallowed={k: tuple(v) for k, v in raw.get("disallowed", {}).items()},
            max_tokens_cap=int(raw["max_tokens_cap"]),
            loop_protocol=_choice(  # type: ignore[arg-type]
                raw["loop_protocol"], get_args(LoopProtocol), f"{alias}.loop_protocol"
            ),
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
    fraction = data["prediction"]["output_fraction"]
    if not 0 < fraction <= 1:
        raise ConfigError("prediction.output_fraction must be in (0, 1]")
    if estimate["chars_per_token"] <= 0 or estimate["headroom"] < 0:
        raise ConfigError("input_estimate: chars_per_token > 0 and headroom >= 0")
    if retry["max_attempts"] < 1:
        raise ConfigError("retry.max_attempts must be at least 1")
    loop, escalation = data["loop"], data["escalation"]
    if loop["max_steps"] < 1 or loop["max_repeats"] < 0 or loop["max_protocol_errors"] < 0:
        raise ConfigError("loop: max_steps >= 1, max_repeats >= 0, max_protocol_errors >= 0")
    for low, high in escalation["next"].items():
        if low not in models or high not in models:
            raise ConfigError(f"escalation.next: unknown model in {low} -> {high}")
    return HarnessConfig(
        base_url=env.get("NEBIUS_BASE_URL") or data["base_url"],
        models=models,
        limits=limits,
        on_missing_usage=_choice(  # type: ignore[arg-type]
            data["on_missing_usage"], get_args(MissingUsagePolicy), "on_missing_usage"
        ),
        chars_per_token=float(estimate["chars_per_token"]),
        input_headroom=float(estimate["headroom"]),
        margin_tokens=int(estimate["margin_tokens"]),
        prediction_output_fraction=float(fraction),
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
        loop=LoopConfig(
            max_steps=int(loop["max_steps"]),
            tool_timeout_s=float(loop["tool_timeout_s"]),
            tool_result_max_tokens=int(loop["tool_result_max_tokens"]),
            max_repeats=int(loop["max_repeats"]),
            max_protocol_errors=int(loop["max_protocol_errors"]),
            json_protocol_response_format=_choice(  # type: ignore[arg-type]
                loop["json_protocol_response_format"],
                ("json_object", "none"),
                "loop.json_protocol_response_format",
            ),
        ),
        escalation=EscalationConfig(int(escalation["max_repairs"]), dict(escalation["next"])),
    )
