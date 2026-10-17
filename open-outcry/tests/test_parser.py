"""Parser unit tests: stocks, numbers, quantities, prices, brackets."""

from __future__ import annotations

from voice_trader.parser.parser import parse
from voice_trader.parser.intent import (
    Action, AssetClass, CommandKind, OrderType, QuantityKind,
)


def test_buy_shares_with_limit():
    cmd = parse("buy 10 shares of Apple at 230")
    assert cmd.kind == CommandKind.ORDER
    o = cmd.order
    assert o.symbol == "AAPL"
    assert o.quantity == 10
    assert o.quantity_kind == QuantityKind.ABSOLUTE
    assert o.order_type == OrderType.LIMIT
    assert o.limit_price == 230.0
    assert o.asset_class == AssetClass.STOCK


def test_sell_half_position():
    cmd = parse("sell half my Tesla position")
    assert cmd.kind == CommandKind.CLOSE
    o = cmd.order
    assert o.symbol == "TSLA"
    assert o.quantity == 0.5
    assert o.quantity_kind == QuantityKind.PERCENT
    assert o.action == Action.SELL


def test_buy_market_default():
    cmd = parse("buy 10 AAPL at market")
    o = cmd.order
    assert o.order_type == OrderType.MARKET
    assert o.limit_price is None
    assert o.quantity == 10


def test_word_numbers():
    assert parse("buy fifty shares of Apple").order.quantity == 50
    assert parse("buy fifteen shares of Apple").order.quantity == 15
    assert parse("buy two hundred shares of Tesla").order.quantity == 200
    assert parse("buy two point five shares of Tesla").order.quantity == 2.5


def test_bracket_order():
    cmd = parse("buy 10 AAPL at 230, stop at 225, target 240")
    o = cmd.order
    assert o.limit_price == 230.0
    assert o.stop_price == 225.0
    assert o.target_price == 240.0
    assert o.bracket is True


def test_stop_loss_only():
    cmd = parse("buy 10 AAPL at 230, stop at 225")
    o = cmd.order
    assert o.limit_price == 230.0
    assert o.stop_price == 225.0
    assert o.order_type == OrderType.STOP_LIMIT


def test_close_without_quantity_defaults_to_all():
    cmd = parse("close my SPY put")
    assert cmd.kind == CommandKind.CLOSE
    assert cmd.order.quantity_kind == QuantityKind.ALL


def test_control_commands():
    assert parse("flatten everything").kind == CommandKind.FLATTEN
    assert parse("cancel all my open orders").kind == CommandKind.CANCEL_ORDERS
    assert parse("stop trading").kind == CommandKind.STOP_TRADING


def test_query_delta_and_position():
    assert parse("what's my delta on my SPY put").kind == CommandKind.QUERY
    assert parse("what are my positions").kind == CommandKind.QUERY


def test_move_stop():
    cmd = parse("move my stop on SPY to 760")
    assert cmd.kind == CommandKind.MOVE_STOP
    assert cmd.order.stop_price == 760.0
    assert cmd.order.symbol == "SPY"


def test_tag():
    cmd = parse("tag this pullback-RS")
    assert cmd.kind == CommandKind.TAG
    assert cmd.tag == "pullback-RS"
