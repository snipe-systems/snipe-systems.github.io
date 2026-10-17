"""Options-fluent parsing: strikes, expiries, spreads."""

from __future__ import annotations

from datetime import date

from voice_trader.parser.parser import parse, spread_to_legs
from voice_trader.parser.intent import Action, CommandKind, OptionType


def test_single_option_with_strike_and_expiry():
    cmd = parse("buy 5 SPY 770 puts expiring this Friday", today=date(2026, 10, 19))
    o = cmd.order
    assert o.option_leg.option_type == OptionType.PUT
    assert o.option_leg.strike == 770
    assert o.option_leg.underlying == "SPY"
    assert o.quantity == 5
    # Monday 2026-10-19 -> this Friday is 2026-10-23.
    assert o.option_leg.expiry == "2026-10-23"


def test_zero_dte():
    cmd = parse("sell my QQQ 0DTE calls", today=date(2026, 10, 19))
    o = cmd.order
    assert o.option_leg.option_type == OptionType.CALL
    assert o.option_leg.expiry == "2026-10-19"


def test_expiry_month_day():
    cmd = parse("buy 1 SPY 760 call expiring Nov 20", today=date(2026, 10, 19))
    assert cmd.order.option_leg.expiry == "2026-11-20"


def test_next_friday():
    cmd = parse("buy 5 SPY 770 puts expiring next Friday", today=date(2026, 10, 19))
    assert cmd.order.option_leg.expiry == "2026-10-30"


def test_put_spread_parses_two_legs():
    cmd = parse("buy the SPY 760/770 put spread", today=date(2026, 10, 19))
    o = cmd.order
    assert o.spread is not None
    assert len(o.spread) == 2
    strikes = sorted(l.strike for l in o.spread)
    assert strikes == [760.0, 770.0]
    assert all(l.option_type == OptionType.PUT for l in o.spread)


def test_spread_direction_buy_put_spread():
    cmd = parse("buy the SPY 760/770 put spread", today=date(2026, 10, 19))
    legs = spread_to_legs(cmd.order.spread, Action.BUY)
    by_strike = {l.strike: l.action for l in legs}
    # Buy put spread: buy higher strike, sell lower strike.
    assert by_strike[770.0] == Action.BUY
    assert by_strike[760.0] == Action.SELL


def test_spread_direction_buy_call_spread():
    cmd = parse("buy the SPY 760/770 call spread", today=date(2026, 10, 19))
    legs = spread_to_legs(cmd.order.spread, Action.BUY)
    by_strike = {l.strike: l.action for l in legs}
    assert by_strike[760.0] == Action.BUY
    assert by_strike[770.0] == Action.SELL
