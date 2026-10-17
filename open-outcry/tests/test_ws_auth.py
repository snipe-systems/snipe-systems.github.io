"""API-key management and WebSocket API tests."""

from __future__ import annotations

import asyncio
import json
import socket

import pytest

from voice_trader import create_session
from voice_trader.interop.auth import ApiKeyStore
from voice_trader.interop.ws_server import WebSocketServer

websockets = pytest.importorskip("websockets")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_key_store_lifecycle(tmp_path):
    store = ApiKeyStore(tmp_path / "keys.json")
    assert store.count() == 0

    key = store.create("my-app")
    assert store.count() == 1
    assert store.verify(key) is True
    assert store.verify("wrong") is False

    listing = store.list()
    assert len(listing) == 1
    assert listing[0]["label"] == "my-app"
    assert "hash" not in listing[0]  # never expose hashes

    prefix = listing[0]["prefix"]
    assert store.revoke(prefix) is True
    assert store.verify(key) is False  # revoked keys fail
    assert store.count() == 0


def test_key_cli_create(tmp_path, capsys):
    from voice_trader.scripts.key_cli import main
    assert main(["--file", str(tmp_path / "k.json"), "create", "--label", "cli"]) == 0
    out = capsys.readouterr().out
    key_line = [ln for ln in out.splitlines() if ln and not ln.startswith("New")][0]
    store = ApiKeyStore(tmp_path / "k.json")
    assert store.verify(key_line) is True


def test_ws_roundtrip(tmp_path):
    session = create_session(journal_path=tmp_path / "t.csv",
                             killswitch_path=tmp_path / "ks")
    port = _free_port()
    server = WebSocketServer(session, host="127.0.0.1", port=port)
    server.start()

    async def client():
        uri = f"ws://127.0.0.1:{port}"
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"text": "buy 10 AAPL at 230"}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert resp["type"] == "response"
            assert resp["pending_confirmation"] is True

            await ws.send(json.dumps({"text": "confirm"}))
            resp2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert resp2["executed"] is True

            # A "filled" event is pushed asynchronously.
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get("type") == "event" and msg["event"].get("type") == "filled":
                    assert msg["event"]["symbol"] == "AAPL"
                    break

    asyncio.run(client())
    server.stop()


def test_ws_auth_required(tmp_path):
    store = ApiKeyStore(tmp_path / "keys.json")
    key = store.create("ws-test")

    session = create_session(journal_path=tmp_path / "t.csv",
                             killswitch_path=tmp_path / "ks")
    port = _free_port()
    server = WebSocketServer(session, host="127.0.0.1", port=port, auth_store=store)
    server.start()

    async def client():
        # Without a key -> server demands auth and closes.
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert msg["type"] == "auth_required"
            await ws.send(json.dumps({"type": "auth", "key": "bad"}))
            with pytest.raises(websockets.exceptions.ConnectionClosed):
                await asyncio.wait_for(ws.recv(), timeout=5)

        # With a valid key -> works.
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert msg["type"] == "auth_required"
            await ws.send(json.dumps({"type": "auth", "key": key}))
            await ws.send(json.dumps({"text": "what are my positions"}))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert resp["type"] == "response"

    asyncio.run(client())
    server.stop()
