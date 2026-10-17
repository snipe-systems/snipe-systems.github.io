"""Resolver ambiguity + risk-engine validation tests."""

from __future__ import annotations

from voice_trader.parser.resolver import Resolver
from voice_trader.parser.parser import parse
from voice_trader.risk.engine import (
    AccountState, Position, RiskConfig, RiskEngine, Violation,
)


def test_resolver_spy_spx_ambiguous():
    r = Resolver()
    res = r.resolve("SPY")
    assert res.found
    assert res.ambiguity, "SPY should be flagged ambiguous with SPX"


def test_resolver_clean_symbol():
    r = Resolver()
    res = r.resolve("AAPL")
    assert res.found
    assert not res.ambiguity


def test_resolver_unknown_symbol():
    r = Resolver()
    res = r.resolve("ZZZZZ")
    assert not res.found


def test_risk_order_value_limit():
    risk = RiskEngine(RiskConfig.from_dict({"max_order_value": 1000.0}))
    cmd = parse("buy 100 shares of Apple at 230")
    acct = AccountState(buying_power=100_000)
    violations = risk.check(cmd, acct, last_price=230.0)
    assert any(v.code == "order_value" for v in violations)


def test_risk_duplicate_blocked():
    risk = RiskEngine(RiskConfig.from_dict({"duplicate_window_seconds": 300}))
    cmd = parse("buy 10 shares of Apple at 230")
    sig = risk.order_signature(cmd)
    risk.record(sig)
    acct = AccountState(buying_power=100_000)
    violations = risk.check(cmd, acct, last_price=230.0)
    assert any(v.code == "duplicate" for v in violations)


def test_risk_daily_loss_blocks():
    risk = RiskEngine(RiskConfig.from_dict({"max_daily_loss": 500.0}))
    cmd = parse("buy 10 shares of Apple at 230")
    acct = AccountState(buying_power=100_000, realized_pnl_today=-600.0)
    violations = risk.check(cmd, acct, last_price=230.0)
    assert any(v.code == "daily_loss" for v in violations)


def test_risk_no_position_to_close():
    risk = RiskEngine(RiskConfig.from_dict({}))
    cmd = parse("sell half my Tesla position")
    acct = AccountState(buying_power=100_000)
    violations = risk.check(cmd, acct, last_price=300.0)
    assert any(v.code == "no_position" for v in violations)


def test_risk_position_size_limit():
    risk = RiskEngine(RiskConfig.from_dict({"max_position_per_symbol": 1000.0}))
    cmd = parse("buy 10 shares of Apple at 230")
    acct = AccountState(buying_power=100_000,
                        positions=[Position("AAPL", 5, 230.0, last_price=230.0)])
    # 5 + 10 = 15 shares * 230 = 3450 > 1000
    violations = risk.check(cmd, acct, last_price=230.0)
    assert any(v.code == "position_size" for v in violations)


def test_risk_trade_count_limit():
    risk = RiskEngine(RiskConfig.from_dict({"max_trades_per_day": 25}))
    cmd = parse("buy 10 shares of Apple at 230")
    acct = AccountState(buying_power=100_000, trades_today=25)
    violations = risk.check(cmd, acct, last_price=230.0)
    assert any(v.code == "trade_limit" for v in violations)


def test_confirm_required_never_false():
    # The risk engine refuses to run if confirmation is disabled.
    risk = RiskEngine(RiskConfig.from_dict({"confirm_required": False}))
    cmd = parse("buy 10 shares of Apple at 230")
    acct = AccountState(buying_power=100_000)
    violations = risk.check(cmd, acct, last_price=230.0)
    assert any(v.code == "confirm_disabled" for v in violations)
