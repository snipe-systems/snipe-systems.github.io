"""Fully local paper broker. No network, no real money, deterministic fills.

Used as the default broker so the whole pipeline (voice -> parse -> validate ->
confirm -> execute -> journal) can run and be tested without any external
account. Prices are seeded from a static map and can be overridden in tests.
"""

from __future__ import annotations

import itertools
import time

from ..parser.intent import Action, Command, OrderType, QuantityKind
from .base import AccountInfo, BrokerAdapter, BrokerResult, Execution, Quote
from ..risk.engine import Position

DEFAULT_PRICES: dict[str, float] = {
    "AAPL": 230.0, "MSFT": 420.0, "TSLA": 300.0, "AMZN": 200.0, "NVDA": 130.0,
    "GOOGL": 175.0, "META": 600.0, "NFLX": 700.0, "SPY": 760.0, "SPX": 7600.0,
    "QQQ": 500.0, "IWM": 220.0, "DIA": 430.0, "VOO": 550.0, "VTI": 290.0,
    "GME": 25.0, "AMC": 4.0, "COIN": 250.0, "PLTR": 70.0, "AMD": 160.0,
    "BTCUSDT": 65000.0, "ETHUSDT": 3200.0, "SOLUSDT": 150.0,
}


class PaperBroker(BrokerAdapter):
    name = "paper"
    is_paper = True

    def __init__(self, initial_cash: float = 100_000.0,
                 prices: dict[str, float] | None = None,
                 market_open: bool = True):
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.prices = dict(prices) if prices is not None else dict(DEFAULT_PRICES)
        self.market_open_flag = market_open
        self._positions: dict[str, dict] = {}
        self._realized = 0.0
        self._trades_today = 0
        self._order_seq = itertools.count(1)

    # --- state helpers ------------------------------------------------------

    def set_price(self, symbol: str, price: float) -> None:
        self.prices[symbol.upper()] = price

    def set_market_open(self, open_: bool) -> None:
        self.market_open_flag = open_

    def _key_for(self, command: Command) -> str:
        o = command.order
        if o is None:
            return ""
        if o.option_leg:
            l = o.option_leg
            return f"{o.symbol}|{l.option_type.value}|{l.strike:g}|{l.expiry or l.expiry_label}"
        if o.spread:
            return "|".join(
                f"{o.symbol}|{l.option_type.value}|{l.strike:g}|{l.expiry or l.expiry_label}"
                for l in o.spread
            )
        return o.symbol or ""

    def _fill_price(self, command: Command) -> float:
        o = command.order
        if o is None:
            return 0.0
        if o.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and o.limit_price is not None:
            return float(o.limit_price)
        if o.asset_class.value == "option":
            # Nominal option premium; simulation only.
            return 2.50
        sym = o.symbol or ""
        return self.prices.get(sym.upper(), 0.0)

    # --- BrokerAdapter ------------------------------------------------------

    def get_account(self) -> AccountInfo:
        positions = []
        for key, pos in self._positions.items():
            positions.append(Position(
                symbol=key,
                quantity=pos["qty"],
                avg_price=pos["avg"],
                last_price=pos.get("last", pos["avg"]),
                asset_class="option" if "|" in key else "stock",
            ))
        equity = self.cash + sum(p.market_value for p in positions)
        return AccountInfo(
            buying_power=self.cash,
            positions=positions,
            open_orders=0,
            realized_pnl_today=self._realized,
            trades_today=self._trades_today,
        )

    def get_quote(self, symbol: str) -> Quote | None:
        sym = symbol.upper()
        px = self.prices.get(sym)
        if px is None:
            return None
        return Quote(symbol=sym, last_price=px, bid=px, ask=px, timestamp=time.time())

    def submit_order(self, command: Command, idempotency_key: str) -> BrokerResult:
        o = command.order
        if o is None:
            return BrokerResult(False, error="no order intent")

        key = self._key_for(command)
        qty = self._resolve_quantity(o)
        if qty <= 0:
            return BrokerResult(False, error="invalid quantity")

        price = self._fill_price(command)
        side = "buy" if o.action in (Action.BUY,) else "sell"
        multiplier = 100 if o.asset_class.value == "option" else 1
        cost = qty * price * multiplier

        if side == "buy":
            if cost > self.cash:
                return BrokerResult(False, error="insufficient buying power")
            self.cash -= cost
            self._apply_position(key, +qty, price)
        else:
            self._apply_position(key, -qty, price)
            self.cash += cost

        self._trades_today += 1
        exec_ = Execution(
            order_id=f"paper-{next(self._order_seq)}",
            symbol=o.symbol or key,
            side=side,
            quantity=qty,
            price=price,
            status="filled",
            idempotency_key=idempotency_key,
        )
        return BrokerResult(True, message="filled", execution=exec_)

    def cancel_all_orders(self) -> BrokerResult:
        return BrokerResult(True, message="no open orders to cancel (paper)")

    def close_all_positions(self) -> BrokerResult:
        if not self._positions:
            return BrokerResult(True, message="no positions to close")
        for key, pos in list(self._positions.items()):
            px = pos.get("last", pos["avg"])
            qty = pos["qty"]  # signed: long (+), short (-)
            # Closing a long returns cash (+qty*px); closing a short costs cash.
            self.cash += qty * px
            del self._positions[key]
        return BrokerResult(True, message="all positions closed")

    def market_status(self) -> str:
        return "open" if self.market_open_flag else "closed"

    def symbol_universe(self) -> set[str]:
        return set(self.prices.keys())

    # --- internals ----------------------------------------------------------

    def _resolve_quantity(self, o) -> float:
        if o.quantity_kind == QuantityKind.ALL:
            key = o.symbol or ""
            pos = self._positions.get(key) or self._positions.get(key.upper())
            return abs(pos["qty"]) if pos else 0.0
        if o.quantity_kind == QuantityKind.PERCENT:
            key = o.symbol or ""
            pos = self._positions.get(key) or self._positions.get(key.upper())
            if not pos:
                return 0.0
            return abs(pos["qty"]) * (o.quantity or 0.0)
        return o.quantity or 0.0

    def _apply_position(self, key: str, delta: float, price: float) -> None:
        pos = self._positions.get(key)
        if pos is None:
            self._positions[key] = {"qty": delta, "avg": price, "last": price}
            return
        if pos["qty"] * delta < 0:
            # reducing / flipping
            closed = min(abs(pos["qty"]), abs(delta))
            if pos["qty"] > 0:
                self._realized += (price - pos["avg"]) * closed
            else:
                self._realized += (pos["avg"] - price) * closed
            pos["qty"] += delta
            if abs(pos["qty"]) < 1e-9:
                del self._positions[key]
                return
        else:
            new_qty = pos["qty"] + delta
            new_avg = (pos["avg"] * abs(pos["qty"]) + price * abs(delta)) / abs(new_qty)
            pos["qty"] = new_qty
            pos["avg"] = new_avg
        pos["last"] = price
