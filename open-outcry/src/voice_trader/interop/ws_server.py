"""Public WebSocket API (requires `websockets`: pip install voice-trader[ws]).

Real-time, bidirectional: clients send `{"text": "..."}` commands and receive
JSON `response` messages, plus pushed `event` messages for fills, blocks,
halts, etc. Optionally authenticated with an API key.

Wire protocol:
  client -> server   {"text": "buy 10 AAPL at 230"}      (a command)
                     {"type": "auth", "key": "..."}       (first message, if auth on)
  server -> client   {"type": "auth_required"}            (only when auth is on)
                     {"type": "response", "text": ..., "state": ..., ...}
                     {"type": "event", "event": {...}}    (streamed lifecycle events)
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading

from ..core.session import TradingSession
from .auth import ApiKeyStore
from .json_mode import response_to_dict

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    websockets = None


class WebSocketServer:
    def __init__(self, session: TradingSession, host: str = "127.0.0.1",
                 port: int = 8011, auth_store: ApiKeyStore | None = None):
        self.session = session
        self.host = host
        self.port = port
        self.auth_store = auth_store
        self.started = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._outbox: queue.Queue = queue.Queue()
        self._clients: set = set()

    def available(self) -> bool:
        return websockets is not None

    def start(self) -> threading.Thread:
        if websockets is None:
            raise RuntimeError("websockets not installed (pip install voice-trader[ws])")
        self.session.events.subscribe(self._on_event)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self.started.wait(timeout=5):
            raise RuntimeError("websocket server failed to start")
        return self._thread

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    # --- internals ----------------------------------------------------------

    def _on_event(self, event: dict) -> None:
        self._outbox.put(event)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        async with websockets.serve(self._handler, self.host, self.port):
            self.started.set()
            broadcaster = asyncio.ensure_future(self._broadcast())
            try:
                while not self._stop.is_set():
                    await asyncio.sleep(0.2)
            finally:
                broadcaster.cancel()

    async def _handler(self, websocket) -> None:
        authed = self.auth_store is None
        if self.auth_store is not None:
            await websocket.send(json.dumps({"type": "auth_required"}))
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=10)
                req = json.loads(raw or "{}")
            except Exception:
                return
            if not self.auth_store.verify(req.get("key", "")):
                await websocket.close(code=4401, reason="unauthorized")
                return
            authed = True

        self._clients.add(websocket)
        try:
            async for raw in websocket:
                try:
                    req = json.loads(raw)
                except json.JSONDecodeError:
                    req = {"text": raw}
                if not isinstance(req, dict):
                    continue
                text = str(req.get("text") or "").strip()
                if not text:
                    continue
                resp = self.session.handle_utterance(text, audio=None)
                await websocket.send(json.dumps(
                    {"type": "response", **response_to_dict(resp)}))
        finally:
            self._clients.discard(websocket)

    async def _broadcast(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            while True:
                try:
                    event = self._outbox.get_nowait()
                except queue.Empty:
                    break
                msg = json.dumps({"type": "event", "event": event})
                for ws in list(self._clients):
                    try:
                        await ws.send(msg)
                    except Exception:
                        self._clients.discard(ws)
