"""The input estimate's calibration source: the operator calls of the first full inc-01
record run (dev split only). tests/fixtures/inc01_operator_inputs.json holds, per call,
the length of the JSON the estimate measures and the prompt_tokens the API reported.
No network."""

import json
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path

from rookwise.harness import load_config
from rookwise.harness.request import estimate_input_tokens

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "inc01_operator_inputs.json"
CALLS = json.loads(FIXTURE.read_text(encoding="utf-8"))["calls"]
MARGIN = 64
# The estimate measures json.dumps({"messages": ..., "response_format": ...}); one user
# message of k plain characters measures k plus this constant.
_EMPTY = len(json.dumps({"messages": [{"role": "user", "content": ""}], "response_format": None}))


def _estimate(call, chars_per_token, headroom):
    messages = [{"role": "user", "content": "x" * (call["payload_characters"] - _EMPTY)}]
    return estimate_input_tokens(messages, None, chars_per_token, MARGIN, headroom)


def test_the_config_ratio_is_the_measured_one_rounded_down():
    chars = sum(c["payload_characters"] for c in CALLS)
    tokens = sum(c["prompt_tokens"] - MARGIN for c in CALLS)
    measured = Decimal(chars) / Decimal(tokens)
    assert len(CALLS) == 71 and str(measured.quantize(Decimal("0.0001"))) == "2.0368"
    config = load_config(env={})
    assert Decimal(str(config.chars_per_token)) == measured.quantize(Decimal("0.01"), ROUND_FLOOR)
    assert config.input_headroom == 0.1 and config.margin_tokens == MARGIN


def test_with_the_headroom_only_the_metrics_slice_stays_short():
    config = load_config(env={})
    short = [
        c["task_id"]
        for c in CALLS
        if _estimate(c, config.chars_per_token, config.input_headroom) < c["prompt_tokens"]
    ]
    assert short == ["t-54"]  # metrics.csv: 1.31 characters per token


def test_the_earlier_ratio_was_short_on_almost_every_operator_call():
    short = [c for c in CALLS if _estimate(c, 2.7, 0.1) < c["prompt_tokens"]]
    assert len(short) == 68
