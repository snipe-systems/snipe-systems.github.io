"""Shared fixtures for the test suite."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from voice_trader.core.session import TradingSession  # noqa: E402
from voice_trader.core.journal import Journal  # noqa: E402
from voice_trader.core.killswitch import KillSwitch  # noqa: E402
from voice_trader.risk.engine import RiskConfig, RiskEngine  # noqa: E402
from voice_trader.parser.resolver import Resolver  # noqa: E402
from voice_trader.broker.paper_broker import PaperBroker  # noqa: E402


class NullLog:
    def transcript(self, *_a, **_k): pass
    def event(self, *_a, **_k): pass
    def debug(self, *_a, **_k): pass
    def error(self, *_a, **_k): pass


def make_risk(**overrides) -> RiskEngine:
    cfg = dict(
        max_order_value=5000.0,
        max_position_per_symbol=10000.0,
        max_daily_loss=500.0,
        max_trades_per_day=25,
        max_open_orders=10,
        confirm_required=True,
        emergency_confirm=True,
        duplicate_window_seconds=300.0,
        price_stale_tolerance_pct=2.0,
        require_market_open=True,
    )
    cfg.update(overrides)
    return RiskEngine(RiskConfig.from_dict(cfg))


@pytest.fixture
def session_factory(tmp_path):
    def _make(positions=None, market_open=True, risk=None, prices=None):
        broker = PaperBroker(market_open=market_open, prices=prices)
        if positions:
            broker._positions = positions
        return TradingSession(
            config={"voice_auth": {"required": False}},
            broker=broker,
            risk=risk or make_risk(),
            resolver=Resolver(broker.symbol_universe()),
            journal=Journal(tmp_path / "trades.csv"),
            killswitch=KillSwitch(tmp_path / "killswitch"),
            log=NullLog(),
            speaker=None,
            voice_verifier=None,
            mode="paper",
        ), broker
    return _make
