"""Salvage the complete part of a JSON reply that was cut off or broken near its end.

`salvage_json` scans the reply once, outside JSON strings, and records every point where
an element is complete: just before each comma between elements, and the end of the text
when it is not inside a string. From the last such point backwards it cuts the text
there, closes the brackets still open at that point (innermost first), parses, and asks
`accept` whether the value will do. The first value accepted is returned with the number
of trailing elements dropped (the separators after the cut, plus the cut-off element when
there is one). Nothing else is repaired: a key without its value, a broken string or a
wrong bracket is never patched, only cut away. A candidate with a duplicate key in any
object is rejected: `json.loads` would keep the last value silently, and a reply that
forgot to close one object and open the next (`},{`) would merge several elements into
one, so the cut moves back to before the duplicate. The caller decides what is acceptable; the
team accepts only findings that validate against the operators' output model and hold at
least one claim, and every citation still goes through the deterministic check.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_CLOSERS = {"{": "}", "[": "]"}
_FENCE = re.compile(r"^\s*```(?:json)?\s*")
# How many cut points are tried, from the end, before giving up.
MAX_CANDIDATES = 400


class _DuplicateKey(ValueError):
    pass


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise _DuplicateKey(keys)
    return dict(pairs)


@dataclass(frozen=True)
class Salvage:
    value: Any
    dropped_elements: int
    cut_at: int  # characters of the reply kept before the brackets were closed


def salvage_json(text: str, accept: Callable[[Any], bool]) -> Salvage | None:
    """The longest complete prefix of `text`, closed and parsed, that `accept` takes; or
    None. `text` must start (after an optional ```json fence) with `{` or `[`."""
    fence = _FENCE.match(text)
    body = text[fence.end() :] if fence else text
    offset = len(text) - len(body)
    start = len(body) - len(body.lstrip())
    if start >= len(body) or body[start] not in _CLOSERS:
        return None
    # (cut position in body, closers for that point, the container the cut is in)
    points: list[tuple[int, str, int]] = []
    stack: list[tuple[str, int]] = []  # (closer, container id) of each open bracket
    containers = 0
    in_string = escaped = False
    for index in range(start, len(body)):
        char = body[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in _CLOSERS:
            containers += 1
            stack.append((_CLOSERS[char], containers))
        elif char in "}]":
            if not stack or stack[-1][0] != char:
                break  # a wrong bracket: only what came before it can be kept
            stack.pop()
            if not stack:
                points.append((index + 1, "", 0))
                break  # the top-level value is complete
        elif char == ",":
            points.append((index, "".join(c for c, _ in reversed(stack)), stack[-1][1]))
    else:
        if not in_string and stack:
            points.append((len(body), "".join(c for c, _ in reversed(stack)), -1))
    for tried, (position, closers, container) in enumerate(reversed(points)):
        if tried >= MAX_CANDIDATES:
            break
        kept = body[start:position].rstrip()
        if kept.endswith((":", ",")):
            continue
        try:
            value = json.loads(kept + closers, object_pairs_hook=_no_duplicate_keys)
        except (json.JSONDecodeError, _DuplicateKey):
            continue
        if accept(value):
            # The elements cut away from the container the cut is in: the one after the
            # cut and every later one in the same container (none when nothing was cut).
            later = sum(1 for p, _, c in points if p > position and c == container)
            dropped = 0 if container <= 0 else 1 + later
            return Salvage(value, dropped, offset + position)
    return None
