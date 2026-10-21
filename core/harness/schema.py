"""JSON Schema helpers for `response_format`.

The Nebius structured output docs do not mention `$ref` or `$defs`, and the only schema
observed to work was flat (docs/HARNESS_RESEARCH.md, "Structured output"), so a schema
with definitions is sent already inlined: `inline_refs` returns a copy with every local
`$ref` replaced by the definition it points to and `$defs` removed. A recursive
reference cannot be inlined and fails loudly.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

# Keywords that only describe a value: a `$ref` sibling may differ from the target in these.
_ANNOTATIONS = frozenset({"title", "description", "default", "examples"})
_PREFIXES = ("#/$defs/", "#/definitions/")


class SchemaError(ValueError):
    """The schema cannot be inlined: a recursive, unknown or non-local `$ref`."""


def inline_refs(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `schema` with no `$ref` left and no `$defs` (or `definitions`). Keys next
    to a `$ref` are kept; one that contradicts the target (other than an annotation) is
    an error. The input is not changed."""
    definitions = {**schema.get("definitions", {}), **schema.get("$defs", {})}
    root = {k: v for k, v in schema.items() if k not in ("$defs", "definitions")}
    return _inline(root, definitions, ())


def _inline(node: Any, definitions: Mapping[str, Any], stack: tuple[str, ...]) -> Any:
    if isinstance(node, list):
        return [_inline(item, definitions, stack) for item in node]
    if not isinstance(node, Mapping):
        return copy.deepcopy(node)
    if "$ref" not in node:
        return {k: _inline(v, definitions, stack) for k, v in node.items()}
    ref = node["$ref"]
    name = next(
        (ref[len(p) :] for p in _PREFIXES if isinstance(ref, str) and ref.startswith(p)), None
    )
    if name is None:
        raise SchemaError(f"only local $ref to $defs can be inlined, not {ref!r}")
    if name not in definitions:
        raise SchemaError(f"$ref {ref!r} names no definition")
    if name in stack:
        raise SchemaError(f"recursive $ref: {' -> '.join((*stack, name))}")
    target = _inline(definitions[name], definitions, (*stack, name))
    for key, value in node.items():
        if key == "$ref":
            continue
        value = _inline(value, definitions, stack)
        if key in target and target[key] != value and key not in _ANNOTATIONS:
            raise SchemaError(f"$ref {ref!r}: {key!r} next to it contradicts the definition")
        target[key] = value
    return target
