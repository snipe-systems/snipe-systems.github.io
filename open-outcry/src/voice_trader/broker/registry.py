"""Broker factory. Chooses and constructs the active adapter from config.

The paper/live boundary is enforced here, not just in the CLI: a live broker is
only ever constructed when `mode == "live"` AND `TRADING_MODE=live` is present
in the environment. Any other combination falls back to paper.
"""

from __future__ import annotations

import os

from .base import BrokerAdapter, BrokerError
from .paper_broker import PaperBroker
from .alpaca_adapter import AlpacaAdapter
from .binance_adapter import BinanceFuturesAdapter


def build_broker(config: dict, mode: str | None = None) -> BrokerAdapter:
    """Build the active broker. `mode` overrides config['mode'] when given."""
    mode = (mode or config.get("mode") or "paper").lower()
    broker_cfg = config.get("broker", {})
    active = config.get("active_broker", "paper").lower()

    live_requested = mode == "live"

    if active == "alpaca":
        a = broker_cfg.get("alpaca", {})
        paper = True
        base_url = a.get("base_url")
        data_url = a.get("data_url")
        if live_requested:
            if os.environ.get("TRADING_MODE", "").lower() != "live":
                raise BrokerError(
                    "live trading requires TRADING_MODE=live in .env (and typing LIVE at startup)")
            paper = False
        return AlpacaAdapter(base_url=base_url, data_url=data_url, paper=paper)

    if active == "binance":
        b = broker_cfg.get("binance", {})
        # Binance adapter is testnet-only by design in this project.
        return BinanceFuturesAdapter(
            base_url=b.get("base_url"),
            testnet=bool(b.get("testnet", True)),
        )

    return PaperBroker(market_open=config.get("risk", {}).get("require_market_open", True) is not False)
