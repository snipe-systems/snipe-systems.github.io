"""Backtest/simulation tests: fills, stale-price re-quote, limits, P&L."""

from __future__ import annotations

from voice_trader.backtest.price_feed import PriceFeed, jump, random_walk
from voice_trader.backtest.replay_broker import ReplayBroker
from voice_trader.backtest.runner import build_session, run_script


def test_stale_price_drift_requires_reconfirm():
    feed = PriceFeed({"AAPL": [230.0, 260.0, 260.0]})
    broker = ReplayBroker(feed)
    session = build_session(broker)

    r1 = session.handle_utterance("buy 10 AAPL at market")
    assert r1.pending_confirmation

    r2 = session.handle_utterance("confirm")
    # 230 -> 260 = +13% > 2% tolerance -> re-confirm, no fill.
    assert r2.pending_confirmation and not r2.executed
    assert "moved" in r2.text

    r3 = session.handle_utterance("confirm")
    assert r3.executed
    assert broker.fill_log[-1].price == 260.0


def test_limit_not_marketable_is_rejected():
    feed = PriceFeed({"AAPL": [230.0, 230.0]})
    broker = ReplayBroker(feed)
    session = build_session(broker)

    session.handle_utterance("buy 10 AAPL at 200")
    r = session.handle_utterance("confirm")
    assert r.executed is False
    assert "not marketable" in r.text
    assert broker.fill_log == []


def test_limit_marketable_fills_at_market():
    feed = PriceFeed({"AAPL": [230.0, 228.0]})
    broker = ReplayBroker(feed)
    session = build_session(broker)

    session.handle_utterance("buy 10 AAPL at 230")
    r = session.handle_utterance("confirm")
    assert r.executed
    assert broker.fill_log[-1].price == 228.0


def test_realized_pnl_roundtrip():
    feed = PriceFeed({"AAPL": [230.0, 230.0, 250.0, 250.0]})
    broker = ReplayBroker(feed)
    session = build_session(broker)

    session.handle_utterance("buy 10 AAPL at market")
    session.handle_utterance("confirm")
    session.handle_utterance("sell all my Apple position")
    r = session.handle_utterance("confirm")
    assert r.executed

    acct = broker.get_account()
    assert acct.realized_pnl_today == (250.0 - 230.0) * 10  # 200.0
    assert acct.positions == []


def test_duplicate_guard_during_replay():
    feed = PriceFeed({"AAPL": [230.0, 230.0, 230.0]})
    broker = ReplayBroker(feed)
    session = build_session(broker)

    session.handle_utterance("buy 10 AAPL at market")
    session.handle_utterance("confirm")
    # Repeating the identical command must not produce a second fill.
    r = session.handle_utterance("buy 10 AAPL at market")
    assert r.executed is False
    assert len(broker.fill_log) == 1


def test_run_script_report_shape():
    feed = random_walk(["AAPL", "TSLA"], n=100, seed=7)
    broker = ReplayBroker(feed)
    session = build_session(broker)
    steps = run_script(session, [
        "buy 10 AAPL at market",
        "sell half my Apple position",
        "what's my delta",
    ])
    assert any(s.executed for s in steps)
    assert steps[-1].executed is False  # query never executes
