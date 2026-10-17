"""The run's event log, in the API contract's events (`rookwise.api.models`).

Every event is validated against the contract when it is emitted. `seq` starts at 1,
`id` is "<run_id>:<seq>" and `ts` never goes back (docs/api.md, "Ordering and
idempotency").
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from rookwise.api.models import SSE_EVENT_ADAPTER, Mode, SseEvent


class EventLog:
    def __init__(
        self,
        run_id: str,
        *,
        mode: Mode = "live",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.run_id = run_id
        self.mode: Mode = mode
        self.events: list[SseEvent] = []
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last: datetime | None = None

    def now(self) -> datetime:
        ts = self._clock()
        if self._last is not None and ts < self._last:
            ts = self._last
        self._last = ts
        return ts

    def emit(self, event_type: str, payload: Any) -> SseEvent:
        seq = len(self.events) + 1
        event = SSE_EVENT_ADAPTER.validate_python(
            {
                "id": f"{self.run_id}:{seq}",
                "seq": seq,
                "run_id": self.run_id,
                "mode": self.mode,
                "ts": self.now(),
                "type": event_type,
                "payload": payload,
            }
        )
        self.events.append(event)
        return event

    def types(self) -> list[str]:
        return [event.type for event in self.events]
