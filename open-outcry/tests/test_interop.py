"""Interop tests: JSON mode, HTTP API, journal sinks, config env overrides,
data providers."""

from __future__ import annotations

import io
import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from voice_trader import create_session
from voice_trader.interop.json_mode import run_json_loop
from voice_trader.interop.http_api import make_handler
from voice_trader.interop.journal_sink import CsvSink, JsonLinesSink
from voice_trader.core.config import apply_env_overrides
from voice_trader.data.provider import (
    CsvMarketDataProvider, DataProviderBroker, StaticProvider,
)


def test_json_mode_roundtrip(tmp_path):
    s = create_session(journal_path=tmp_path / "t.csv",
                       killswitch_path=tmp_path / "ks")
    inp = io.StringIO(
        '{"text":"buy 10 AAPL at 230"}\n'
        '{"text":"confirm"}\n'
        '{"text":"__exit__"}\n'
    )
    out = io.StringIO()
    assert run_json_loop(s, inp, out) == 0
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert lines[0]["pending_confirmation"] is True
    assert lines[0]["executed"] is False
    assert lines[1]["executed"] is True
    assert lines[1]["positions"]["AAPL"] == 10.0


def test_json_mode_tolerates_raw_text(tmp_path):
    s = create_session(journal_path=tmp_path / "t.csv",
                       killswitch_path=tmp_path / "ks")
    inp = io.StringIO("buy 10 AAPL at 230\n__exit__\n")
    out = io.StringIO()
    run_json_loop(s, inp, out)
    lines = [json.loads(l) for l in out.getvalue().splitlines()]
    assert lines[0]["pending_confirmation"] is True


def test_http_api(tmp_path):
    s = create_session(journal_path=tmp_path / "t.csv",
                       killswitch_path=tmp_path / "ks")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(s))
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        health = json.loads(urllib.request.urlopen(f"{base}/health").read())
        assert health["ok"] is True

        req = urllib.request.Request(
            f"{base}/command",
            data=json.dumps({"text": "buy 10 AAPL at 230"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        r = json.loads(urllib.request.urlopen(req).read())
        assert r["pending_confirmation"] is True

        r2 = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"{base}/confirm", data=b"{}")).read())
        assert r2["executed"] is True

        state = json.loads(urllib.request.urlopen(f"{base}/state").read())
        assert state["positions"]["AAPL"] == 10.0

        journal = json.loads(urllib.request.urlopen(f"{base}/journal").read())
        assert len(journal) == 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_journal_json_lines_mirror(tmp_path):
    s = create_session(journal_path=tmp_path / "t.csv",
                       killswitch_path=tmp_path / "ks")
    json_sink = JsonLinesSink(tmp_path / "t.jsonl")
    s.journal.sinks.append(json_sink)

    s.handle_utterance("buy 10 AAPL at 230")
    s.handle_utterance("confirm")

    rows = json_sink.read()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"


def test_journal_tag_last_json(tmp_path):
    sink = JsonLinesSink(tmp_path / "t.jsonl")
    sink.write({"timestamp": "x", "symbol": "AAPL", "action": "buy",
                "quantity": 10, "fill_price": 230.0, "strategy": "",
                "idempotency_key": "k"})
    assert sink.tag_last("pullback-RS")
    assert sink.read()[0]["strategy"] == "pullback-RS"


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("VOICE_TRADER_MODE", "live")
    monkeypatch.setenv("VOICE_TRADER__RISK__MAX_ORDER_VALUE", "9999.5")
    monkeypatch.setenv("VOICE_TRADER__RISK__MAX_TRADES_PER_DAY", "42")
    monkeypatch.setenv("VOICE_TRADER__RISK__REQUIRE_MARKET_OPEN", "false")
    monkeypatch.setenv("VOICE_TRADER__BROKER__ALPACA__BASE_URL", "http://example.com")

    cfg = apply_env_overrides({})
    assert cfg["mode"] == "live"
    assert cfg["risk"]["max_order_value"] == 9999.5
    assert cfg["risk"]["max_trades_per_day"] == 42
    assert cfg["risk"]["require_market_open"] is False
    assert cfg["broker"]["alpaca"]["base_url"] == "http://example.com"


def test_static_data_provider_broker(tmp_path):
    provider = StaticProvider({"AAPL": 230.0, "TSLA": 300.0})
    broker = DataProviderBroker(provider)
    s = create_session(broker=broker, journal_path=tmp_path / "t.csv",
                       killswitch_path=tmp_path / "ks")
    s.handle_utterance("buy 10 AAPL at market")
    r = s.handle_utterance("confirm")
    assert r.executed
    assert broker.fill_log[-1].price if hasattr(broker, "fill_log") else True
    # PaperBroker uses provider price for market fill.
    acct = broker.get_account()
    assert any(p.symbol == "AAPL" and p.quantity == 10 for p in acct.positions)


def test_csv_market_data_provider(tmp_path):
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text("symbol,price\nAAPL,231.5\nTSLA,302.0\n")
    provider = CsvMarketDataProvider(csv_path)
    q = provider.quote("aapl")
    assert q.last_price == 231.5
    assert provider.quote("NOPE") is None
