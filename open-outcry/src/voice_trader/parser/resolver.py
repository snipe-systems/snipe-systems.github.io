"""Symbol resolution and ambiguity detection.

The resolver turns a candidate ticker into a canonical symbol and decides
whether it is unambiguous enough to act on. Near-neighbour tickers that a
speech recognizer could plausibly confuse (SPY vs SPX) are reported as
ambiguous so the caller is forced to ask rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .symbols import COMMON_TICKERS, KNOWN_NAMES


# Known pairs a recognizer commonly confuses.
KNOWN_CONFUSABLES: list[set[str]] = [
    {"SPY", "SPX"},
    {"GOOG", "GOOGL"},
    {"IWM", "DIA"},
    {"BTC", "ETH"},
]


@dataclass
class ResolutionResult:
    symbol: str | None
    found: bool
    confidence: float
    ambiguity: list[str] = field(default_factory=list)
    reason: str = ""


def _edit_distance(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 1:
        return 2
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[lb]


class Resolver:
    def __init__(self, universe: set[str] | None = None):
        base = set(COMMON_TICKERS) | set(KNOWN_NAMES.values())
        self.universe = base if universe is None else (base | set(universe))
        self._neighbors: dict[str, list[str]] = {}

    def add_universe(self, symbols: set[str]) -> None:
        self.universe |= set(symbols)

    def resolve(self, symbol: str | None) -> ResolutionResult:
        if not symbol:
            return ResolutionResult(None, False, 0.0, reason="no symbol")

        sym = symbol.upper().strip()

        if sym in self.universe:
            amb = self._near_neighbors(sym)
            if amb:
                return ResolutionResult(sym, True, 0.6, ambiguity=amb,
                                        reason="near-neighbour tickers")
            return ResolutionResult(sym, True, 1.0)

        # Not found at all -> report closest matches as candidates.
        candidates = [s for s in self.universe if _edit_distance(sym, s) <= 2]
        return ResolutionResult(None, False, 0.0, ambiguity=candidates,
                                reason=f"symbol {sym} not found")

    def _near_neighbors(self, sym: str) -> list[str]:
        if sym in self._neighbors:
            return self._neighbors[sym]
        result: list[str] = []
        for group in KNOWN_CONFUSABLES:
            if sym in group:
                result = sorted(group - {sym})
                break
        self._neighbors[sym] = result
        return result
