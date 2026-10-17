"""Broker adapter interface.

Every broker (Alpaca, Binance, or a local paper simulator) implements this
interface. The execution engine only talks to BrokerAdapter, never to a
concrete SDK, so the broker is swappable at runtime via config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..parser.intent import Command
from ..risk.engine import Position


class BrokerError(Exception):
    """Raised when a broker API is unreachable or rejects a request."""


@dataclass
class Quote:
    symbol: str
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    timestamp: float = 0.0


@dataclass
class AccountInfo:
    buying_power: float
    positions: list[Position]
    open_orders: int = 0
    realized_pnl_today: float = 0.0
    trades_today: int = 0


@dataclass
class Execution:
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: str
    idempotency_key: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrokerResult:
    success: bool
    message: str = ""
    execution: Execution | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.success


class BrokerAdapter(ABC):
    name: str = "base"
    is_paper: bool = True

    @abstractmethod
    def get_account(self) -> AccountInfo:
        ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote | None:
        ...

    @abstractmethod
    def submit_order(self, command: Command, idempotency_key: str) -> BrokerResult:
        ...

    @abstractmethod
    def cancel_all_orders(self) -> BrokerResult:
        ...

    @abstractmethod
    def close_all_positions(self) -> BrokerResult:
        ...

    @abstractmethod
    def market_status(self) -> str:
        """One of 'open', 'premarket', 'afterhours', 'closed'."""

    def symbol_universe(self) -> set[str]:
        """Optional list of symbols this broker knows about."""
        return set()

    def resolve_option_contract(self, underlying: str, strike: float,
                                option_type: str, expiry: str) -> str | None:
        """Map (underlying, strike, type, expiry) to a broker contract symbol."""
        return None
