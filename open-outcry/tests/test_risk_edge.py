"""Boundary/edge-case tests for the risk engine limits."""

from __future__ import annotations

from voice_trader.risk.engine import (
    AccountState, Position, RiskConfig, RiskEngine,
)
from voice_trader.parser.parser import parse


def _check(risk, cmd_text, account, last_price):
    cmd = parse(cmd_text)
    return {v.code for v in risk.check(cmd, account, last_price=last_price)}


def test_order_value_exactly_at_limit_is_allowed():
    risk = RiskEngine(RiskConfig.from_dict({"max_order_value": 1000.0}))
    # 10 shares * 100 = 1000 -> exactly at limit, not over.
    codes = _check(risk, "buy 10 shares of Apple at 100",
                   AccountState(buying_power=100_000), 100.0)
    assert "order_value" not in codes


def test_order_value_just_over_is_blocked():
    risk = RiskEngine(RiskConfig.from_dict({"max_order_value": 1000.0}))
    codes = _check(risk, "buy 11 shares of Apple at 100",
                   AccountState(buying_power=100_000), 100.0)
    assert "order_value" in codes


def test_daily_loss_exactly_at_limit_is_blocked():
    risk = RiskEngine(RiskConfig.from_dict({"max_daily_loss": 500.0}))
    codes = _check(risk, "buy 10 shares of Apple at 100",
                   AccountState(buying_power=100_000, realized_pnl_today=-500.0), 100.0)
    assert "daily_loss" in codes


def test_daily_loss_just_under_is_allowed():
    risk = RiskEngine(RiskConfig.from_dict({"max_daily_loss": 500.0}))
    codes = _check(risk, "buy 10 shares of Apple at 100",
                   AccountState(buying_power=100_000, realized_pnl_today=-499.0), 100.0)
    assert "daily_loss" not in codes


def test_trade_count_exactly_at_limit_is_blocked():
    risk = RiskEngine(RiskConfig.from_dict({"max_trades_per_day": 25}))
    codes = _check(risk, "buy 10 shares of Apple at 100",
                   AccountState(buying_power=100_000, trades_today=25), 100.0)
    assert "trade_limit" in codes


def test_trade_count_just_under_is_allowed():
    risk = RiskEngine(RiskConfig.from_dict({"max_trades_per_day": 25}))
    codes = _check(risk, "buy 10 shares of Apple at 100",
                   AccountState(buying_power=100_000, trades_today=24), 100.0)
    assert "trade_limit" not in codes


def test_buying_power_exactly_spent_is_allowed():
    risk = RiskEngine(RiskConfig.from_dict({}))
    codes = _check(risk, "buy 100 shares of Apple at 100",
                   AccountState(buying_power=10_000), 100.0)
    assert "buying_power" not in codes


def test_buying_power_just_over_is_blocked():
    risk = RiskEngine(RiskConfig.from_dict({}))
    codes = _check(risk, "buy 101 shares of Apple at 100",
                   AccountState(buying_power=10_000), 100.0)
    assert "buying_power" in codes


def test_zero_quantity_blocked():
    risk = RiskEngine(RiskConfig.from_dict({}))
    codes = _check(risk, "buy 0 shares of Apple at 100",
                   AccountState(buying_power=100_000), 100.0)
    assert "bad_quantity" in codes


def test_negative_quantity_blocked():
    risk = RiskEngine(RiskConfig.from_dict({}))
    cmd = parse("buy -10 shares of Apple at 100")
    codes = {v.code for v in risk.check(cmd, AccountState(buying_power=100_000), 100.0)}
    # negative number words aren't parsed as quantity; quantity becomes None -> bad_quantity
    assert "bad_quantity" in codes
