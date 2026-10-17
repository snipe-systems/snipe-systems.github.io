"""A tiny in-process pub/sub event bus.

The session emits lifecycle events (transcript, pending, filled, blocked,
halted, ...) which the WebSocket server and any external integration can
subscribe to for real-time streaming.
"""

from __future__ import annotations

from typing import Callable


class EventBus:
    def __init__(self):
        self._subscribers: list[Callable[[dict], None]] = []

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def emit(self, event: dict) -> None:
        for cb in list(self._subscribers):
            try:
                cb(dict(event))
            except Exception:
                # A broken subscriber must never break the trading pipeline.
                pass
