"""Synthetic and file-backed price feeds for simulation/backtesting.

A `PriceFeed` is an ordered series of prices per symbol. Each call to
`advance(symbol)` returns the current price and moves to the next tick,
modelling time passing between quote polls — which is exactly what the
pipeline's stale-price protection needs to be tested against.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path


class PriceFeed:
    def __init__(self, series: dict[str, list[float]]):
        self.series = {str(k).upper(): [float(x) for x in v] for k, v in series.items()}
        self._idx = {k: 0 for k in self.series}
        self._current = {k: (v[0] if v else None) for k, v in self.series.items()}

    def current(self, symbol: str) -> float | None:
        return self._current.get(symbol.upper())

    def advance(self, symbol: str) -> float | None:
        """Return the current price and advance to the next tick."""
        s = symbol.upper()
        if s not in self.series:
            return None
        px = self._current[s]
        self._idx[s] += 1
        if self._idx[s] < len(self.series[s]):
            self._current[s] = self.series[s][self._idx[s]]
        return px

    def remaining(self, symbol: str) -> int:
        s = symbol.upper()
        return max(0, len(self.series.get(s, [])) - self._idx.get(s, 0))


def random_walk(symbols: list[str], n: int = 200, start: float = 100.0,
                vol: float = 0.01, seed: int = 42) -> PriceFeed:
    """Geometric random walk for each symbol (deterministic via seed)."""
    rng = random.Random(seed)
    series: dict[str, list[float]] = {}
    for sym in symbols:
        price = start
        out = []
        for _ in range(n):
            price *= max(0.001, 1.0 + rng.gauss(0.0, vol))
            out.append(round(price, 2))
        series[sym] = out
    return PriceFeed(series)


def jump(symbol: str, *, before: float, after: float, ticks_before: int = 2,
         ticks_after: int = 2) -> PriceFeed:
    """A flat series with a single sharp jump, to exercise stale-price re-quote."""
    series = [before] * ticks_before + [after] * ticks_after
    return PriceFeed({symbol: series})


def from_csv(path: str | Path, symbol_col: str = "symbol",
             price_col: str = "price") -> PriceFeed:
    """Load a real historical price CSV. Columns are preserved in file order
    per symbol. Expects at least a symbol column and a price column."""
    series: dict[str, list[float]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            sym = row[symbol_col].upper()
            try:
                series.setdefault(sym, []).append(float(row[price_col]))
            except (ValueError, KeyError):
                continue
    return PriceFeed(series)
