"""In-process pub/sub used by every component to report what is happening.

The dashboard, the console and the phone all subscribe to the same stream, so what
you see on screen is exactly what the brain did (no separate logging paths).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

# Event types that are high-volume and should not be kept in history.
_EPHEMERAL = {"frame"}


class EventBus:
    def __init__(self, history: int = 400) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._history: deque[dict] = deque(maxlen=history)

    def emit(self, type_: str, **data: Any) -> dict:
        event = {"type": type_, "ts": time.time(), **data}
        if type_ not in _EPHEMERAL:
            self._history.append(event)
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # slow consumer: drop the oldest item rather than blocking the brain
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass
        return event

    def subscribe(self, maxsize: int = 500) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def recent(self, limit: int = 200, types: set[str] | None = None) -> list[dict]:
        items = [e for e in self._history if types is None or e["type"] in types]
        return items[-limit:]
