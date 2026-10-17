"""Pluggable market-data sources.

Feed the tool prices from anywhere: a static dict, a CSV file, or your own
streaming source. Implement `MarketDataProvider.quote(symbol) -> Quote | None`
and hand it to a `DataProviderBroker`.
"""

from __future__ import annotations

import csv
import time
from abc import ABC, abstractmethod
from pathlib import Path

from ..broker.base import Quote
from ..broker.paper_broker import PaperBroker


class MarketDataProvider(ABC):
    @abstractmethod
    def quote(self, symbol: str) -> Quote | None:
        ...


class StaticProvider(MarketDataProvider):
    def __init__(self, prices: dict[str, float]):
        self.prices = {k.upper(): float(v) for k, v in prices.items()}

    def quote(self, symbol: str) -> Quote | None:
        px = self.prices.get(symbol.upper())
        if px is None:
            return None
        return Quote(symbol=symbol.upper(), last_price=px, bid=px, ask=px,
                     timestamp=time.time())


class CsvMarketDataProvider(MarketDataProvider):
    """Latest price per symbol from a CSV with `symbol` and `price` columns."""

    def __init__(self, path: str | Path, symbol_col: str = "symbol",
                 price_col: str = "price"):
        self._prices: dict[str, float] = {}
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    self._prices[row[symbol_col].upper()] = float(row[price_col])
                except (ValueError, KeyError):
                    continue

    def quote(self, symbol: str) -> Quote | None:
        px = self._prices.get(symbol.upper())
        if px is None:
            return None
        return Quote(symbol=symbol.upper(), last_price=px, bid=px, ask=px,
                     timestamp=time.time())


class DataProviderBroker(PaperBroker):
    """A local (paper) broker whose quotes come from a MarketDataProvider."""

    def __init__(self, provider: MarketDataProvider, initial_cash: float = 100_000.0,
                 market_open: bool = True):
        super().__init__(initial_cash=initial_cash, market_open=market_open)
        self.provider = provider

    def get_quote(self, symbol: str) -> Quote | None:
        return self.provider.quote(symbol)

    def symbol_universe(self) -> set[str]:
        # Sample symbols by probing nothing; callers can extend via Resolver.
        return set()
