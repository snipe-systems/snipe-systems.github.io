"""Minimal Black-Scholes option delta for the "what's my delta" query."""

from __future__ import annotations

import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def option_delta(S: float, K: float, T_years: float, option_type: str,
                 sigma: float = 0.30, r: float = 0.02) -> float:
    """Black-Scholes delta. T_years = time to expiry in years."""
    if T_years <= 0:
        T_years = 1e-6
    if S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T_years) / (sigma * math.sqrt(T_years))
    if option_type.lower() == "call":
        return _norm_cdf(d1)
    return _norm_cdf(d1) - 1.0
