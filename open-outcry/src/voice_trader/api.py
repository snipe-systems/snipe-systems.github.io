"""Public Python API.

Other software can drive voice-trader programmatically:

    from voice_trader import create_session, run_command

    session = create_session(mode="paper")
    resp = run_command(session, "buy 10 shares of Apple at 230")
    assert resp.pending_confirmation
    fill = run_command(session, "confirm")
    print(fill.text)  # "Filled. buy 10 AAPL at 230."

This module only imports lightweight core modules; optional deps (audio, STT,
speaker verification, TTS, live broker SDKs) are pulled in lazily and are not
required for text-driven or paper-broker usage.
"""

from __future__ import annotations

from pathlib import Path

from .core.session import TradingSession, Response
from .core.state import State
from .core.journal import Journal
from .core.killswitch import KillSwitch
from .core.config import load_config, load_env
from .parser.parser import parse, spread_to_legs
from .parser.resolver import Resolver
from .parser.intent import (
    Action,
    AssetClass,
    Command,
    CommandKind,
    OptionLeg,
    OptionType,
    OrderIntent,
    OrderType,
    QuantityKind,
    describe_command,
)
from .risk.engine import (
    AccountState,
    Position,
    RiskConfig,
    RiskEngine,
    Violation,
)
from .broker.base import BrokerAdapter, BrokerError, BrokerResult, Execution, Quote
from .broker.paper_broker import PaperBroker, DEFAULT_PRICES
from .data.provider import (
    CsvMarketDataProvider,
    DataProviderBroker,
    MarketDataProvider,
    StaticProvider,
)
from .interop.journal_sink import CsvSink, JsonLinesSink, JournalSink, XlsxSink


def create_session(*, broker: BrokerAdapter | None = None,
                   config: dict | None = None,
                   mode: str = "paper",
                   risk: RiskConfig | None = None,
                   journal_path: str | Path = "journal/trades.csv",
                   killswitch_path: str | Path = "config/killswitch",
                   seed_positions: dict[str, float] | None = None,
                   prices: dict[str, float] | None = None) -> TradingSession:
    """Build a ready-to-use session. Defaults to the local paper broker.

    - `broker`: pass your own BrokerAdapter to target Alpaca/Binance/custom.
    - `seed_positions`: pre-open positions in the paper broker, e.g.
      {"TSLA": 20.0} (average entry = current paper price).
    - `prices`: override paper-broker prices, e.g. {"AAPL": 230.0}.
    """
    cfg = dict(config or {})
    cfg.setdefault("voice_auth", {})["required"] = cfg.get("voice_auth", {}).get("required", False)

    if broker is None:
        paper = PaperBroker(market_open=True, prices=prices)
        if seed_positions:
            for sym, qty in seed_positions.items():
                px = paper.prices.get(sym.upper(), paper.prices.get(sym, 0.0))
                paper._positions[sym.upper()] = {"qty": qty, "avg": px, "last": px}
        broker = paper

    return TradingSession(
        config=cfg,
        broker=broker,
        risk=RiskEngine(risk or RiskConfig.from_dict(cfg.get("risk", {}))),
        resolver=Resolver(broker.symbol_universe() or None),
        journal=Journal(journal_path),
        killswitch=KillSwitch(killswitch_path),
        log=_NullLog(),
        speaker=None,
        voice_verifier=None,
        mode=mode,
    )


def run_command(session: TradingSession, text: str) -> Response:
    """Run a single utterance through the full pipeline."""
    return session.handle_utterance(text, audio=None)


class _NullLog:
    def __getattr__(self, _n):
        return lambda *a, **k: None


__all__ = [
    "create_session", "run_command",
    "TradingSession", "Response", "State",
    "Journal", "KillSwitch", "load_config", "load_env",
    "parse", "spread_to_legs", "Resolver",
    "Action", "AssetClass", "Command", "CommandKind", "OptionLeg", "OptionType",
    "OrderIntent", "OrderType", "QuantityKind", "describe_command",
    "AccountState", "Position", "RiskConfig", "RiskEngine", "Violation",
    "BrokerAdapter", "BrokerError", "BrokerResult", "Execution", "Quote",
    "PaperBroker", "DEFAULT_PRICES",
    "MarketDataProvider", "StaticProvider", "CsvMarketDataProvider", "DataProviderBroker",
    "JournalSink", "CsvSink", "JsonLinesSink", "XlsxSink",
]
