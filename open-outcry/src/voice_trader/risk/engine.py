"""Risk engine. Enforces every limit in code.

Limits are checked here, not merely "suggested". Both the pre-confirm and
pre-execute stages call `check()`; any violation blocks the order and returns
a human-readable reason. The duplicate-order guard uses a content signature
plus a rolling time window so a repeated voice command never becomes a second
fill.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from ..parser.intent import Action, Command, CommandKind, QuantityKind


@dataclass
class RiskConfig:
    max_order_value: float = 5000.0
    max_position_per_symbol: float = 10000.0
    max_daily_loss: float = 500.0
    max_trades_per_day: int = 25
    max_open_orders: int = 10
    confirm_required: bool = True
    emergency_confirm: bool = True
    duplicate_window_seconds: float = 300.0
    price_stale_tolerance_pct: float = 2.0
    require_market_open: bool = True
    option_premium_estimate: float = 5.0

    @classmethod
    def from_dict(cls, d: dict) -> "RiskConfig":
        return cls(
            max_order_value=float(d.get("max_order_value", 5000.0)),
            max_position_per_symbol=float(d.get("max_position_per_symbol", 10000.0)),
            max_daily_loss=float(d.get("max_daily_loss", 500.0)),
            max_trades_per_day=int(d.get("max_trades_per_day", 25)),
            max_open_orders=int(d.get("max_open_orders", 10)),
            confirm_required=bool(d.get("confirm_required", True)),
            emergency_confirm=bool(d.get("emergency_confirm", True)),
            duplicate_window_seconds=float(d.get("duplicate_window_seconds", 300.0)),
            price_stale_tolerance_pct=float(d.get("price_stale_tolerance_pct", 2.0)),
            require_market_open=bool(d.get("require_market_open", True)),
            option_premium_estimate=float(d.get("option_premium_estimate", 5.0)),
        )


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_price: float
    last_price: float | None = None
    asset_class: str = "stock"

    @property
    def market_value(self) -> float:
        px = self.last_price if self.last_price else self.avg_price
        return abs(self.quantity) * px


@dataclass
class AccountState:
    buying_power: float = 100_000.0
    positions: list[Position] = field(default_factory=list)
    realized_pnl_today: float = 0.0
    trades_today: int = 0
    open_orders: int = 0

    def position(self, symbol: str) -> Position | None:
        for p in self.positions:
            if p.symbol.upper() == symbol.upper():
                return p
        return None


@dataclass
class Violation:
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class RiskEngine:
    def __init__(self, config: RiskConfig):
        self.config = config
        self._recent: dict[str, float] = {}

    # --- duplicate / idempotency -------------------------------------------

    @staticmethod
    def order_signature(command: Command) -> str:
        """Stable content hash used for both idempotency and duplicate checks."""
        o = command.order
        if o is None:
            parts = [command.kind.value]
        else:
            parts = [
                o.action.value,
                o.symbol or "",
                o.asset_class.value,
                str(o.quantity),
                o.quantity_kind.value,
                o.order_type.value,
                str(o.limit_price),
                str(o.stop_price),
                str(o.target_price),
            ]
            if o.spread:
                parts += [f"{l.underlying}:{l.option_type.value}:{l.strike}:{l.expiry}" for l in o.spread]
            elif o.option_leg:
                l = o.option_leg
                parts += [f"{l.underlying}:{l.option_type.value}:{l.strike}:{l.expiry}"]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

    def is_duplicate(self, signature: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        self._prune(now)
        if signature in self._recent:
            age = now - self._recent[signature]
            if age <= self.config.duplicate_window_seconds:
                return True
        return False

    def record(self, signature: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self._recent[signature] = now
        self._prune(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self.config.duplicate_window_seconds
        stale = [k for k, t in self._recent.items() if t < cutoff]
        for k in stale:
            del self._recent[k]

    # --- checks ------------------------------------------------------------

    def check(self, command: Command, account: AccountState,
              last_price: float | None = None, now: float | None = None) -> list[Violation]:
        violations: list[Violation] = []

        if self.config.confirm_required is False:
            violations.append(Violation("confirm_disabled",
                "Confirmation requirement has been disabled; refusing to trade."))

        is_trade = command.kind in (CommandKind.ORDER, CommandKind.CLOSE)

        if is_trade and account.realized_pnl_today <= -self.config.max_daily_loss:
            violations.append(Violation("daily_loss",
                f"Daily loss limit hit (${-account.realized_pnl_today:,.2f} lost). Trading blocked."))

        if is_trade:
            if account.trades_today >= self.config.max_trades_per_day:
                violations.append(Violation("trade_limit",
                    f"Max trades per day ({self.config.max_trades_per_day}) reached."))

            if account.open_orders >= self.config.max_open_orders:
                violations.append(Violation("open_orders",
                    f"Max open orders ({self.config.max_open_orders}) reached."))

            sig = self.order_signature(command)
            if self.is_duplicate(sig, now):
                violations.append(Violation("duplicate",
                    "An identical order was already sent recently. Refusing to double it up."))

            violations += self._check_position_and_value(command, account, last_price)

        return violations

    def _check_position_and_value(self, command: Command, account: AccountState,
                                  last_price: float | None) -> list[Violation]:
        o = command.order
        violations: list[Violation] = []
        if o is None:
            return violations

        symbol = o.symbol
        price = last_price or o.limit_price

        # Quantity sanity.
        if o.quantity_kind in (QuantityKind.PERCENT, QuantityKind.ALL):
            pos = account.position(symbol) if symbol else None
            if pos is None or abs(pos.quantity) == 0:
                violations.append(Violation("no_position",
                    f"No position in {symbol} to close or reduce."))
                return violations
            if o.quantity_kind == QuantityKind.ALL:
                qty = abs(pos.quantity)
            else:
                qty = abs(pos.quantity) * (o.quantity or 0.0)
        else:
            qty = o.quantity or 0.0

        if qty <= 0:
            violations.append(Violation("bad_quantity",
                "Quantity is missing or not positive."))
            return violations

        # Notional estimate: the order-value cap is a RISK-INCREASE guard, so
        # it applies to buys only. Sells/closes reduce risk and must never be
        # blocked by size (blocking an exit could trap a position).
        if o.action == Action.BUY and price is not None and price > 0:
            multiplier = 100 if o.asset_class.value == "option" else 1
            notional = qty * price * multiplier
            if notional > self.config.max_order_value:
                violations.append(Violation("order_value",
                    f"Order value ${notional:,.2f} exceeds limit ${self.config.max_order_value:,.2f}."))

        # Position size after trade.
        if symbol and price is not None and price > 0:
            pos = account.position(symbol)
            current = pos.market_value if pos else 0.0
            is_reduce = o.action == Action.SELL or o.action == Action.CLOSE
            after = current - qty * price if is_reduce else current + qty * price
            after = max(after, 0.0)
            if after > self.config.max_position_per_symbol:
                violations.append(Violation("position_size",
                    f"Position in {symbol} would be ${after:,.2f}, exceeding limit "
                    f"${self.config.max_position_per_symbol:,.2f}."))

        # Buying power.
        if price is not None and price > 0 and o.action == Action.BUY:
            multiplier = 100 if o.asset_class.value == "option" else 1
            cost = qty * price * multiplier
            if cost > account.buying_power:
                violations.append(Violation("buying_power",
                    f"Order cost ${cost:,.2f} exceeds buying power ${account.buying_power:,.2f}."))

        return violations
