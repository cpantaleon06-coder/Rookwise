"""The calibrated input estimate against real prompt token counts.

tests/fixtures/cassettes/team_smoke_inputs.json holds the inputs of 4 calls of the first
live smoke run with the prompt_tokens the API reported for them. The estimate that sizes
a reservation must never be below that count. No network.
"""

import json
from pathlib import Path

import pytest

from rookwise.harness import load_config
from rookwise.harness.request import estimate_input_tokens

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cassettes" / "team_smoke_inputs.json"
CALLS = json.loads(FIXTURE.read_text(encoding="utf-8"))["calls"]


def _estimate(call, chars_per_token, headroom, margin=64):
    return estimate_input_tokens(
        call["messages"], call["response_format"], chars_per_token, margin, headroom
    )


def test_the_calibration_is_in_config():
    config = load_config(env={})
    assert (config.chars_per_token, config.input_headroom) == (2.7, 0.1)


@pytest.mark.parametrize("index", range(len(CALLS)), ids=[c["model"] for c in CALLS])
def test_the_reservation_estimate_is_never_below_the_real_prompt_tokens(index):
    config = load_config(env={})
    call = CALLS[index]
    estimate = _estimate(call, config.chars_per_token, config.input_headroom)
    assert estimate >= call["prompt_tokens"]


def test_the_old_ratio_undercounted_and_the_headroom_is_needed():
    # chars / 3 was below the real count for the prompts with logs, and so was 2.7 alone.
    assert any(_estimate(c, 3, 0.0) < c["prompt_tokens"] for c in CALLS)
    assert any(_estimate(c, 2.7, 0.0) < c["prompt_tokens"] for c in CALLS)


def test_the_headroom_scales_the_characters_not_the_margin():
    messages = [{"role": "user", "content": "x" * 198}]  # 270 JSON characters in all
    assert estimate_input_tokens(messages, None, 2.7, 64) == 100 + 64
    assert estimate_input_tokens(messages, None, 2.7, 64, 0.1) == 110 + 64
