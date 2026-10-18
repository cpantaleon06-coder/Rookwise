"""Filter B: a keyword/regex stage-0 filter, designed once from the dev incidents only.

Frozen on 2026-10-17 before any filter was scored on the test incidents. Each rule names the
dev evidence that motivated it; a rule was kept only if it did not flood the dev logs with
routine lines (the slow-request bound sits above the slowest routine request in dev, 2,400 ms).

A line is kept when any rule matches it. No context lines are added. Works on plain text and
JSON lines alike, because the rules read `key=value` and `"key": value` the same way.
"""

from __future__ import annotations

import re

# severity words (dev-1 handshake/502/breaker, dev-3 GC/OOM/kill)
SEVERITY = re.compile(r"\b(ERROR|FATAL|CRITICAL|WARN|WARNING)\b")
# change markers (dev-2 config bundle and config.diff, dev-3 the release)
CHANGE = re.compile(r"config\.diff|config bundle applied|deploy finished|rollback")
# a job or check that silently did not do its work (dev-1 cert rotation skipped, policy denied)
SKIPPED = re.compile(r"\bskipped[\"=: ]+[1-9]|denied|expired|expir")

_NUM = r"[\"]?\s*[:=]\s*(-?\d+(?:\.\d+)?)"


def _num(key: str, line: str) -> float | None:
    m = re.search(rf"\b{key}{_NUM}", line)
    return float(m.group(1)) if m else None


def _thresholds(line: str) -> bool:
    # dev-2 slow but successful catalog requests (5,120 and 6,830 ms)
    lat = _num("latency_ms", line)
    if lat is not None and lat >= 3000:
        return True
    cpu = _num("cpu_pct", line)  # dev-2 database CPU 97%
    if cpu is not None and cpu >= 85:
        return True
    hit = _num("hit_ratio", line)  # dev-2 empty product cache
    if hit is not None and hit <= 0.5:
        return True
    used, top = _num("heap_used_mb", line), _num("heap_max_mb", line)  # dev-3 heap growth
    if used is not None and top and used / top >= 0.7:
        return True
    return False


def keep_line(line: str) -> bool:
    return bool(
        SEVERITY.search(line) or CHANGE.search(line) or SKIPPED.search(line) or _thresholds(line)
    )


def kept_lines(lines: list[str]) -> set[int]:
    """1-based numbers of the kept lines."""
    return {n for n, line in enumerate(lines, 1) if keep_line(line)}
