"""core/slicing.py: deterministic slices at line boundaries, absolute line numbers, overlap,
the calibrated size limit, oversized lines, empty sources and the coverage check.

The property tests run over seeded random sources (no extra test dependency), so a
failure always reproduces. No network.
"""

import json
import random

import pytest

from rookwise.evidence import split_lines
from rookwise.harness import load_config
from rookwise.slicing import (
    SlicingConfig,
    coverage,
    estimate_tokens,
    load_slicing_config,
    numbered_line,
    slice_bundle,
    slice_source,
)
from rookwise.team.auditor import render_source

CPT, HEADROOM = 2.7, 0.1


def _slices(text, budget=200, overlap=3, source_id="logs/app.log"):
    return slice_source(source_id, text, budget, overlap, chars_per_token=CPT, headroom=HEADROOM)


def _log(count, seed=0, width=(20, 90)):
    rng = random.Random(seed)
    lines = []
    for n in range(count):
        body = "".join(
            rng.choice('abcdefghij =:/-_.0123456789"\\') for _ in range(rng.randint(*width))
        )
        lines.append(f"2026-03-04T02:{n // 60 % 60:02d}:{n % 60:02d}Z INFO {body}")
    return "\n".join(lines) + "\n"


def _cases():
    rng = random.Random(20261019)
    for case in range(60):
        count = rng.randint(1, 400)
        budget = rng.choice([60, 120, 200, 500, 2000])
        overlap = rng.randint(0, 12)
        yield _log(count, seed=case, width=(0, 160)), budget, overlap


def test_the_config_is_data_and_uses_the_calibrated_estimate():
    config = load_slicing_config()
    harness = load_config(env={})
    assert (config.max_slice_tokens, config.overlap_lines) == (12000, 10)
    assert (config.chars_per_token, config.headroom) == (
        harness.chars_per_token,
        harness.input_headroom,
    )


def test_lines_keep_their_absolute_numbers_in_the_format_agents_already_read():
    text = "first line\nsecond line\nthird line\n"
    (only,) = _slices(text, budget=10_000)
    assert (only.slice_id, only.line_start, only.line_end, only.line_count) == (
        "logs/app.log:1-3",
        1,
        3,
        3,
    )
    body = only.text.split("\n", 1)[1]
    assert body == render_source("logs/app.log", text).split("\n", 1)[1]
    assert body.splitlines()[1] == numbered_line(2, "second line") == "2: second line"
    many = _slices(_log(50), budget=200, overlap=0)
    later = many[2]
    first_line = later.text.split("\n")[1]
    assert first_line.startswith(f"{later.line_start}: ")
    assert first_line == numbered_line(
        later.line_start, split_lines(_log(50))[later.line_start - 1]
    )


CASES = list(_cases())


@pytest.mark.parametrize("case", range(len(CASES)))
def test_every_line_is_covered_in_order_within_the_budget(case):
    text, budget, overlap = CASES[case]
    count = len(split_lines(text))
    slices = _slices(text, budget=budget, overlap=overlap)
    assert coverage(slices, count) == []
    assert [s.index for s in slices] == list(range(len(slices)))
    starts = [s.line_start for s in slices]
    ends = [s.line_end for s in slices]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert ends == sorted(ends) and slices[0].line_start == 1 and ends[-1] == count
    for s in slices:
        assert s.line_start <= s.line_end
        # The size is the harness's estimate of the rendered text, and it stays in budget.
        chars = len(json.dumps(s.text))
        assert s.tokens == estimate_tokens(chars, CPT, HEADROOM)
        assert s.tokens <= budget or (s.oversized and s.line_start == s.line_end)
        lines = s.text.split("\n")[1:]
        assert len(lines) == s.line_end - s.line_start + 1  # whole lines only
    for before, after in zip(slices, slices[1:], strict=False):
        assert after.line_start <= before.line_end + 1  # no gap
        if not before.oversized and not after.oversized:
            assert before.line_end - after.line_start + 1 <= overlap


def test_consecutive_slices_overlap_by_the_configured_lines():
    slices = _slices(_log(300), budget=600, overlap=5)
    assert len(slices) > 3
    for before, after in zip(slices, slices[1:], strict=False):
        assert before.line_end - after.line_start + 1 == 5


def test_the_same_input_gives_the_same_slices():
    text = _log(250, seed=7)
    assert _slices(text) == _slices(text)
    assert slice_bundle({"a": text, "b": text[::-1]}, _config()) == slice_bundle(
        {"a": text, "b": text[::-1]}, _config()
    )


def test_a_line_larger_than_the_budget_is_its_own_oversized_slice_and_kept_whole():
    huge = "x" * 5000
    text = "short one\nshort two\n" + huge + "\nshort three\n"
    slices = _slices(text, budget=200, overlap=3)
    (big,) = [s for s in slices if s.oversized]
    assert (big.line_start, big.line_end) == (3, 3)
    assert big.text.endswith(numbered_line(3, huge))  # never truncated
    assert big.tokens > 200
    assert coverage(slices, 4) == []
    after = slices[slices.index(big) + 1]
    assert after.line_start == 4  # no overlap into an oversized line


def test_an_empty_source_has_no_slices_and_is_reported():
    assert _slices("") == []
    bundle = slice_bundle({"empty.txt": "", "app.log": "one\ntwo\n"}, _config())
    assert bundle.empty_sources == ("empty.txt",)
    assert [s.source_id for s in bundle.slices] == ["app.log"]
    assert bundle.line_counts == {"empty.txt": 0, "app.log": 2}


def test_coverage_reports_the_ranges_no_slice_covers():
    slices = _slices(_log(100), budget=200, overlap=0)
    assert coverage(slices, 100) == []
    missing = [s for s in slices if s.index != 1]
    gap = slices[1]
    assert coverage(missing, 100) == [(slices[0].line_end + 1, gap.line_end)]
    assert coverage([], 5) == [(1, 5)]
    assert coverage(slices, 0) == []


def test_bad_settings_are_refused():
    for budget, overlap in ((0, 1), (10, -1)):
        with pytest.raises(ValueError):
            _slices("a\n", budget=budget, overlap=overlap)


def _config():
    return SlicingConfig(
        max_slice_tokens=300, overlap_lines=4, chars_per_token=CPT, headroom=HEADROOM
    )
