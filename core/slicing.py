"""Deterministic source slicing with absolute line numbers. No model, no network.

The hierarchy's operators and the single-model baselines (D1 in docs/DECISIONS.md) read
the evidence in slices made here, so this module imports nothing from `rookwise.team`.

A slice is a run of whole lines of one source, rendered the way agents already read a
source: a header with the source id and the line range, then each line as
`<number>: <line>` with its 1-based number in the whole source (`numbered_line`). The
number is only a label: a citation quotes the raw line, without the prefix.

- Slices split only at line boundaries and come in line order.
- Consecutive slices overlap by `overlap_lines` lines, so evidence at a boundary is never
  cut. The overlap shrinks only when the next line would not fit with it, and there is
  none next to an oversized line.
- A slice's size is the harness's calibrated input estimate of its text (JSON characters
  divided by `chars_per_token`, times 1 + `headroom`, config/harness.json
  `input_estimate`), and it never passes `max_slice_tokens`, except:
- a single line larger than the budget becomes its own slice, flagged `oversized`; it is
  never dropped and never truncated.
- An empty source gives no slices; `slice_bundle` lists it in `empty_sources`.

`coverage(slices, line_count)` returns the line ranges no slice covers (none, when the
slicer is right). `max_slice_tokens` and `overlap_lines` live in config/slicing.json.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rookwise.evidence import split_lines

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "slicing.json"


def numbered_line(number: int, line: str) -> str:
    """A source line as agents read it: its 1-based number, a colon, the raw line."""
    return f"{number}: {line}"


def slice_header(source_id: str, line_start: int, line_end: int, line_count: int) -> str:
    return (
        f"Source {source_id}, lines {line_start}-{line_end} of {line_count} "
        "(cite it by this id and these line numbers):"
    )


@dataclass(frozen=True)
class SlicingConfig:
    max_slice_tokens: int
    overlap_lines: int
    chars_per_token: float
    headroom: float

    def __post_init__(self) -> None:
        if self.max_slice_tokens < 1 or self.overlap_lines < 0:
            raise ValueError("max_slice_tokens >= 1 and overlap_lines >= 0")
        if self.chars_per_token <= 0 or self.headroom < 0:
            raise ValueError("chars_per_token > 0 and headroom >= 0")


def load_slicing_config(path: Path = CONFIG_PATH) -> SlicingConfig:
    """config/slicing.json, with the calibrated estimate from config/harness.json."""
    from rookwise.harness.config import load_config  # the harness owns the estimate

    data = json.loads(path.read_text(encoding="utf-8"))
    harness = load_config(env={})
    return SlicingConfig(
        max_slice_tokens=int(data["max_slice_tokens"]),
        overlap_lines=int(data["overlap_lines"]),
        chars_per_token=harness.chars_per_token,
        headroom=harness.input_headroom,
    )


@dataclass(frozen=True)
class Slice:
    source_id: str
    slice_id: str  # "<source_id>:<line_start>-<line_end>"
    index: int  # 0-based position among the source's slices
    line_start: int  # 1-based, absolute in the source
    line_end: int
    line_count: int  # lines in the whole source
    text: str  # header and numbered lines, as the agent reads them
    tokens: int  # the calibrated estimate of `text`
    oversized: bool = False


@dataclass(frozen=True)
class BundleSlices:
    slices: tuple[Slice, ...]
    empty_sources: tuple[str, ...]
    line_counts: Mapping[str, int]

    @property
    def oversized(self) -> tuple[str, ...]:
        return tuple(s.slice_id for s in self.slices if s.oversized)


def _escaped(text: str) -> int:
    """Characters `text` takes inside a JSON string (the harness's estimate reads JSON)."""
    return len(json.dumps(text)) - 2


def estimate_tokens(chars: int, chars_per_token: float, headroom: float) -> int:
    """The harness's calibrated estimate for `chars` JSON characters (no template margin)."""
    return math.ceil(round(chars * (1 + headroom) / chars_per_token, 6))


def slice_source(
    source_id: str,
    text: str,
    max_slice_tokens: int,
    overlap_lines: int,
    *,
    chars_per_token: float,
    headroom: float,
) -> list[Slice]:
    """The ordered slices of one source (none for an empty source)."""
    SlicingConfig(max_slice_tokens, overlap_lines, chars_per_token, headroom)  # validates
    lines = split_lines(text)
    count = len(lines)
    if not count:
        return []
    # cost[i]: the JSON characters line i + 1 adds: a line break and the numbered line.
    prefix = [0]
    for number, line in enumerate(lines, 1):
        prefix.append(prefix[-1] + 2 + _escaped(numbered_line(number, line)))

    def size(first: int, last: int) -> int:
        header = _escaped(slice_header(source_id, first, last, count))
        chars = 2 + header + prefix[last] - prefix[first - 1]
        return estimate_tokens(chars, chars_per_token, headroom)

    def fits(first: int, last: int) -> bool:
        return size(first, last) <= max_slice_tokens

    slices: list[Slice] = []
    start = 1
    while True:
        oversized = not fits(start, start)
        end = start
        if not oversized:
            while end < count and fits(start, end + 1):
                end += 1
        body = "".join("\n" + numbered_line(n, lines[n - 1]) for n in range(start, end + 1))
        slices.append(
            Slice(
                source_id=source_id,
                slice_id=f"{source_id}:{start}-{end}",
                index=len(slices),
                line_start=start,
                line_end=end,
                line_count=count,
                text=slice_header(source_id, start, end, count) + body,
                tokens=size(start, end),
                oversized=oversized,
            )
        )
        if end >= count:
            return slices
        following = end + 1
        for overlap in range(overlap_lines, 0, -1):
            candidate = max(end + 1 - overlap, start + 1)
            if not oversized and fits(candidate, end + 1):
                following = candidate
                break
        start = following


def slice_bundle(sources: Mapping[str, str], config: SlicingConfig | None = None) -> BundleSlices:
    """Every source's slices, sources in the order given."""
    config = config or load_slicing_config()
    slices: list[Slice] = []
    empty: list[str] = []
    counts: dict[str, int] = {}
    for source_id, text in sources.items():
        found = slice_source(
            source_id,
            text,
            config.max_slice_tokens,
            config.overlap_lines,
            chars_per_token=config.chars_per_token,
            headroom=config.headroom,
        )
        counts[source_id] = len(split_lines(text))
        if not found:
            empty.append(source_id)
        slices.extend(found)
    return BundleSlices(tuple(slices), tuple(empty), counts)


def coverage(slices: Sequence[Slice], line_count: int) -> list[tuple[int, int]]:
    """The line ranges (first, last) of 1..line_count that no slice covers."""
    covered = sorted((s.line_start, s.line_end) for s in slices)
    gaps: list[tuple[int, int]] = []
    following = 1
    for first, last in covered:
        if first > following:
            gaps.append((following, min(first - 1, line_count)))
        following = max(following, last + 1)
    if following <= line_count:
        gaps.append((following, line_count))
    return [gap for gap in gaps if gap[0] <= gap[1]]
