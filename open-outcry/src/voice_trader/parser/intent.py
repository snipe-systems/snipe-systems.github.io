"""Structured command/order model produced by the parser and consumed everywhere else.

Every field that the parser derives carries a confidence score. The safety
contract is: any field whose confidence is below the configured threshold is
treated as MISSING and the system must ask for clarification rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    CLOSE = "close"  # close/reduce an existing position


class AssetClass(str, Enum):
    STOCK = "stock"
    OPTION = "option"
    CRYPTO = "crypto"
    UNKNOWN = "unknown"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class QuantityKind(str, Enum):
    ABSOLUTE = "absolute"     # explicit number of shares/contracts
    PERCENT = "percent"       # fraction of existing position ("half", "25%")
    ALL = "all"               # entire existing position


class CommandKind(str, Enum):
    ORDER = "order"                       # buy/sell something new
    CLOSE = "close"                       # close/reduce a position
    FLATTEN = "flatten"                   # close ALL positions
    CANCEL_ORDERS = "cancel_orders"       # cancel all open orders
    MOVE_STOP = "move_stop"               # modify a stop order/price
    QUERY = "query"                       # informational ("what's my delta")
    STOP_TRADING = "stop_trading"         # kill switch (voice)
    TAG = "tag"                           # tag the last trade
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass
class OptionLeg:
    """A single option contract reference."""
    underlying: str
    option_type: OptionType
    strike: float
    expiry: str | None = None             # ISO date YYYY-MM-DD when resolvable
    expiry_label: str | None = None       # raw label e.g. "this Friday", "0DTE"
    action: Action = Action.BUY
    confidence: float = 0.0

    def describe(self) -> str:
        label = self.expiry or self.expiry_label or "?"
        ot = self.option_type.value if self.option_type else "option"
        strike = f"{self.strike:g} " if self.strike is not None else ""
        und = self.underlying or "?"
        return f"{und} {strike}{ot} exp {label}"


@dataclass
class OrderIntent:
    action: Action = Action.BUY
    symbol: str | None = None             # underlying ticker for options too
    asset_class: AssetClass = AssetClass.UNKNOWN
    quantity: float | None = None
    quantity_kind: QuantityKind = QuantityKind.ABSOLUTE
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    option_leg: OptionLeg | None = None   # single option
    spread: list[OptionLeg] | None = None # multi-leg (vertical/iron)
    bracket: bool = False                 # stop + target attached to one order
    tag: str | None = None
    confidence: dict[str, float] = field(default_factory=dict)

    def conf(self, key: str) -> float:
        return self.confidence.get(key, 0.0)


@dataclass
class Command:
    kind: CommandKind
    raw_text: str
    order: OrderIntent | None = None
    query_topic: str | None = None        # e.g. "delta", "position"
    query_symbol: str | None = None
    tag: str | None = None
    confidence: dict[str, float] = field(default_factory=dict)
    ambiguity: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def conf(self, key: str) -> float:
        return self.confidence.get(key, 0.0)

    def is_confident(self, threshold: float) -> bool:
        """True if every recorded confidence is >= threshold and no ambiguity."""
        if self.ambiguity:
            return False
        if not self.confidence:
            return True
        return all(c >= threshold for c in self.confidence.values())


# ---------------------------------------------------------------------------
# Human-readable description used for spoken read-back on the confirmation gate.
# ---------------------------------------------------------------------------

def describe_command(cmd: Command) -> str:
    o = cmd.order
    if cmd.kind == CommandKind.FLATTEN:
        return "Close all positions (flatten everything)"
    if cmd.kind == CommandKind.CANCEL_ORDERS:
        return "Cancel all open orders"
    if cmd.kind == CommandKind.STOP_TRADING:
        return "Stop all trading (kill switch)"
    if cmd.kind == CommandKind.QUERY:
        return f"Query: {cmd.query_topic or ''} {cmd.query_symbol or ''}".strip()
    if cmd.kind == CommandKind.TAG:
        return f"Tag last trade as: {cmd.tag}"
    if cmd.kind == CommandKind.MOVE_STOP and o:
        return f"Move stop on {o.symbol} to {o.stop_price}"
    if cmd.kind == CommandKind.HELP:
        return "Show help"
    if o is None:
        return cmd.raw_text

    parts: list[str] = []
    verb = o.action.value
    parts.append(verb)

    qty = _describe_quantity(o)
    if qty:
        parts.append(qty)

    if o.spread:
        legs = " / ".join(leg.describe() for leg in o.spread)
        parts.append(legs)
    elif o.option_leg:
        parts.append(o.option_leg.describe())
    elif o.symbol:
        parts.append(o.symbol)

    if o.order_type == OrderType.LIMIT and o.limit_price is not None:
        parts.append(f"limit {o.limit_price}")
    elif o.order_type == OrderType.STOP and o.stop_price is not None:
        parts.append(f"stop {o.stop_price}")
    elif o.order_type == OrderType.STOP_LIMIT:
        parts.append(f"stop {o.stop_price} limit {o.limit_price}")
    if o.bracket:
        if o.stop_price is not None:
            parts.append(f"stop {o.stop_price}")
        if o.target_price is not None:
            parts.append(f"target {o.target_price}")
    return " ".join(parts)


def _describe_quantity(o: OrderIntent) -> str:
    if o.quantity_kind == QuantityKind.ALL:
        return "all of"
    if o.quantity_kind == QuantityKind.PERCENT and o.quantity is not None:
        pct = o.quantity * 100
        return f"{pct:g}% of"
    if o.quantity is not None:
        return f"{o.quantity:g}"
    return ""
