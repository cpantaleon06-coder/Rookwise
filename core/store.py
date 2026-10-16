"""The shared store behind one interface (docs/ARCHITECTURE.md, "Messages and shared store").

Messages carry references such as `store://r-003/results/t-014`; content lives here. The
production store (Supabase Postgres or SQLite) is still an open decision, so
`InMemoryStore` is the only implementation: enough for the single operator runner and
for tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class Store(Protocol):
    def get(self, ref: str) -> Any: ...

    def put(self, ref: str, value: Any) -> None: ...


class InMemoryStore:
    def __init__(self, items: Mapping[str, Any] | None = None) -> None:
        self._items: dict[str, Any] = dict(items or {})

    def get(self, ref: str) -> Any:
        try:
            return self._items[ref]
        except KeyError:
            raise KeyError(f"nothing stored at {ref}") from None

    def put(self, ref: str, value: Any) -> None:
        self._items[ref] = value
