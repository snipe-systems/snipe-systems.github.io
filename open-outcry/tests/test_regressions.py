"""Regression tests for issues found during independent verification."""

from __future__ import annotations

from voice_trader.core.confirmation import ConfirmationGate
from voice_trader.parser.parser import parse
from voice_trader.parser.intent import QuantityKind


def test_confirmation_token_based():
    g = ConfirmationGate()
    cmd = parse("buy 10 shares of Apple at 230")
    g.begin(cmd, "buy 10 AAPL", 230.0, "abc")

    # Substring false-positives must NOT confirm.
    assert g.interpret("disconfirm") == "pending"
    g.begin(cmd, "buy 10 AAPL", 230.0, "abc")
    assert g.interpret("unconfirmed") == "pending"
    g.begin(cmd, "buy 10 AAPL", 230.0, "abc")
    assert g.interpret("never confirm") == "cancelled"

    # "confirm now" must confirm (the old substring "no" bug cancelled it).
    g.begin(cmd, "buy 10 AAPL", 230.0, "abc")
    assert g.interpret("confirm now") == "confirmed"


def test_option_close_closes_position(session_factory):
    session, broker = session_factory()
    broker._positions["SPY|put|770|2026-11-20"] = {"qty": 5.0, "avg": 2.5, "last": 2.5}

    r = session.handle_utterance("close my SPY put")
    assert r.pending_confirmation, r.text  # must not be blocked as "no position"

    r2 = session.handle_utterance("confirm")
    assert r2.executed, r2.text
    assert broker.get_account().positions == []


def test_option_close_with_explicit_strike(session_factory):
    session, broker = session_factory()
    broker._positions["SPY|put|770|2026-11-20"] = {"qty": 5.0, "avg": 2.5, "last": 2.5}

    session.handle_utterance("close my SPY 770 put")
    r2 = session.handle_utterance("confirm")
    assert r2.executed, r2.text
    assert broker.get_account().positions == []


def test_strike_not_misread_as_quantity():
    cmd = parse("close my SPY 770 put")
    assert cmd.order.quantity is None
    assert cmd.order.quantity_kind == QuantityKind.ALL
    assert cmd.order.option_leg.strike == 770.0


def test_market_option_cannot_bypass_value_limit(session_factory):
    session, broker = session_factory(risk=__import__("tests.conftest",
                                                      fromlist=["make_risk"]).make_risk(
        max_order_value=5000.0, option_premium_estimate=5.0))
    # 1,000,000 contracts * 100 * $5 premium = $500M >> limit.
    r = session.handle_utterance("buy 1000000 SPY 770 puts expiring this Friday")
    assert r.blocked, r.text
    assert "order_value" in r.text or "Order value" in r.text


def test_live_broker_requires_env(monkeypatch):
    from voice_trader.broker.registry import build_broker
    from voice_trader.broker.base import BrokerError
    monkeypatch.delenv("TRADING_MODE", raising=False)
    cfg = {"mode": "live", "active_broker": "alpaca", "broker": {"alpaca": {}}}
    try:
        build_broker(cfg)
        assert False, "expected BrokerError"
    except BrokerError:
        pass


def test_csv_formula_injection_sanitized(tmp_path):
    import csv
    from voice_trader.interop.journal_sink import CsvSink
    sink = CsvSink(tmp_path / "t.csv")
    sink.write({"timestamp": "x", "symbol": "AAPL", "action": "buy",
                "quantity": 1, "fill_price": 1.0,
                "strategy": "=HYPERLINK(\"http://evil\")", "idempotency_key": "k"})
    with open(tmp_path / "t.csv", newline="") as f:
        rows = list(csv.reader(f))
    strategy = rows[-1][5]  # strategy column
    assert strategy.startswith("'=")  # neutralized, not a formula
