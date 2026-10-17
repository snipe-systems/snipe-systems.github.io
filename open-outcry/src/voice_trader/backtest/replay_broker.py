"""Replay broker: fills orders against a PriceFeed, one tick per quote poll.

Extends the local PaperBroker with realistic fill semantics:
  - market orders fill at the current tick
  - limit orders fill only if marketable (buy: market <= limit; sell: market >= limit)
  - non-marketable limits are rejected, like a real exchange

This is what makes backtesting the *execution* logic (not just parsing) meaningful.
"""

from __future__ import annotations

import itertools
import time

from ..parser.intent import Action, AssetClass, Command, OrderType
from ..broker.base import BrokerResult, Execution, Quote
from ..broker.paper_broker import PaperBroker
from .price_feed import PriceFeed


class ReplayBroker(PaperBroker):
    name = "replay"
    is_paper = True

    def __init__(self, feed: PriceFeed, initial_cash: float = 100_000.0):
        super().__init__(initial_cash=initial_cash, market_open=True)
        self.feed = feed
        self.fill_log: list[Execution] = []
        self._last_quote: dict[str, float] = {}

    def get_quote(self, symbol: str) -> Quote | None:
        px = self.feed.advance(symbol)
        if px is None:
            return None
        self._last_quote[symbol.upper()] = px
        return Quote(symbol=symbol.upper(), last_price=px, bid=px, ask=px,
                     timestamp=time.time())

    def submit_order(self, command: Command, idempotency_key: str) -> BrokerResult:
        o = command.order
        if o is None:
            return BrokerResult(False, error="no order intent")

        key = self._key_for(command)
        qty = self._resolve_quantity(o)
        if qty <= 0:
            return BrokerResult(False, error="invalid quantity")

        symbol = o.symbol or ""
        market_px = self._last_quote.get(symbol.upper(), self.feed.current(symbol))
        side = "buy" if o.action == Action.BUY else "sell"

        # Limit marketability.
        if o.order_type == OrderType.LIMIT and o.limit_price is not None:
            if market_px is None:
                return BrokerResult(False, error="no price available")
            if side == "buy" and market_px > o.limit_price:
                return BrokerResult(False,
                    error=f"limit {o.limit_price:g} not marketable (market {market_px:g})")
            if side == "sell" and market_px < o.limit_price:
                return BrokerResult(False,
                    error=f"limit {o.limit_price:g} not marketable (market {market_px:g})")
            fill_price = market_px
        else:
            fill_price = market_px
            if fill_price is None or fill_price <= 0:
                return BrokerResult(False, error="no price available")

        multiplier = 100 if o.asset_class == AssetClass.OPTION else 1
        cost = qty * fill_price * multiplier

        if side == "buy":
            if cost > self.cash:
                return BrokerResult(False, error="insufficient buying power")
            self.cash -= cost
            self._apply_position(key, +qty, fill_price)
        else:
            self._apply_position(key, -qty, fill_price)
            self.cash += cost

        self._trades_today += 1
        exec_ = Execution(
            order_id=f"replay-{next(self._order_seq)}",
            symbol=symbol,
            side=side,
            quantity=qty,
            price=fill_price,
            status="filled",
            idempotency_key=idempotency_key,
        )
        self.fill_log.append(exec_)
        return BrokerResult(True, message="filled", execution=exec_)

    def symbol_universe(self) -> set[str]:
        return set(self.feed.series.keys())
