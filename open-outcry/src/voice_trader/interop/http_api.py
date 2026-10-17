"""Local HTTP API (stdlib only — no extra dependencies).

Run `voice-trader --serve` (default http://127.0.0.1:8010). Any HTTP client —
curl, a dashboard, another service — can drive the trader:

    POST /command   {"text": "buy 10 AAPL at 230"}   -> order response JSON
    POST /confirm                                     -> confirm pending order
    POST /cancel                                      -> cancel pending order
    POST /halt                                        -> kill switch
    GET  /health                                      -> {"ok": true}
    GET  /state                                       -> session + positions + cash
    GET  /positions                                   -> open positions
    GET  /journal                                     -> trade journal rows

Bind to 127.0.0.1 by default so it is never exposed to the network unless you
explicitly pass --host 0.0.0.0.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..core.session import TradingSession
from .auth import ApiKeyStore
from .json_mode import response_to_dict


def _state(session: TradingSession) -> dict:
    acct = session.broker.get_account()
    return {
        "halted": session.halted or session.killswitch.is_halted(),
        "pending_confirmation": session.gate.is_pending(),
        "mode": session.mode,
        "broker": session.broker.name,
        "cash": acct.buying_power,
        "realized_pnl": acct.realized_pnl_today,
        "positions": {p.symbol: p.quantity for p in acct.positions},
    }


def make_handler(session: TradingSession, auth_store: ApiKeyStore | None = None):
    class Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            if auth_store is None:
                return True
            header = self.headers.get("Authorization", "")
            key = header.removeprefix("Bearer ").strip() if header.lower().startswith("bearer ") else ""
            return auth_store.verify(key)

        def _send(self, code: int, obj) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0:
                return {}
            try:
                return json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return {}

        def do_GET(self):  # noqa: N802
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            path = self.path.split("?")[0]
            routes = {
                "/health": lambda: {"ok": True},
                "/state": lambda: _state(session),
                "/positions": lambda: _state(session)["positions"],
                "/journal": lambda: session.journal.read(),
                "/mode": lambda: {"mode": session.mode},
            }
            if path in routes:
                self._send(200, routes[path]())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            path = self.path.split("?")[0]
            req = self._body()
            if path == "/command":
                resp = session.handle_utterance(str(req.get("text", "")), audio=None)
                self._send(200, response_to_dict(resp))
            elif path == "/confirm":
                self._send(200, response_to_dict(session.handle_utterance("confirm")))
            elif path == "/cancel":
                self._send(200, response_to_dict(session.handle_utterance("cancel")))
            elif path == "/halt":
                session.halted = True
                session.killswitch.trigger_voice()
                self._send(200, {"halted": True})
            else:
                self._send(404, {"error": "not found"})

        def log_message(self, *args):  # silence request logging
            pass

    return Handler


def serve(session: TradingSession, host: str = "127.0.0.1", port: int = 8010,
          auth_store: ApiKeyStore | None = None) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(session, auth_store))
    print(f"voice-trader HTTP API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
