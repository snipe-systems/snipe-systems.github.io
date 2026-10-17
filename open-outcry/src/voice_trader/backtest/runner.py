"""Backtest runner: replays a command script through the full session against a
price feed and produces an audit report (fills, blocks, P&L, positions).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..core.session import TradingSession
from ..core.journal import Journal
from ..core.killswitch import KillSwitch
from ..core.logging import AuditLogger
from ..core.state import State
from ..risk.engine import RiskConfig, RiskEngine
from ..parser.resolver import Resolver
from ..broker.base import BrokerAdapter
from .replay_broker import ReplayBroker


class _NullLog:
    def __getattr__(self, _n):
        return lambda *a, **k: None


def build_session(broker: BrokerAdapter, risk: RiskConfig | None = None,
                  journal_path: str | Path | None = None,
                  config: dict | None = None) -> TradingSession:
    cfg = config or {"voice_auth": {"required": False}}
    risk = risk or RiskConfig.from_dict({})
    if journal_path is None:
        journal_path = Path(tempfile.mkdtemp(prefix="voice-trader-bt-")) / "trades.csv"
    return TradingSession(
        config=cfg,
        broker=broker,
        risk=RiskEngine(risk),
        resolver=Resolver(broker.symbol_universe() or None),
        journal=Journal(journal_path),
        killswitch=KillSwitch(cfg.get("killswitch", {}).get("path", "config/killswitch")),
        log=_NullLog(),
        speaker=None,
        voice_verifier=None,
        mode="paper",
    )


@dataclass
class Step:
    command: str
    state: State
    executed: bool
    blocked: bool
    pending: bool
    message: str
    fill_price: float | None = None
    positions: dict = field(default_factory=dict)


def _snapshot(broker) -> dict:
    return {p.symbol: p.quantity for p in broker.get_account().positions}


def run_script(session: TradingSession, script: list[str],
               auto_confirm: bool = True) -> list[Step]:
    """Feed commands; auto-confirm pending orders when auto_confirm is True."""
    steps: list[Step] = []
    broker = session.broker
    for cmd in script:
        resp = session.handle_utterance(cmd, audio=None)
        if resp.pending_confirmation and auto_confirm:
            resp = session.handle_utterance("confirm", audio=None)
        fill_price = None
        if resp.executed and isinstance(broker, ReplayBroker) and broker.fill_log:
            fill_price = broker.fill_log[-1].price
        steps.append(Step(
            command=cmd,
            state=resp.state,
            executed=resp.executed,
            blocked=resp.blocked,
            pending=resp.pending_confirmation,
            message=resp.text,
            fill_price=fill_price,
            positions=_snapshot(broker),
        ))
    return steps


def report(steps: list[Step], broker: BrokerAdapter) -> str:
    acct = broker.get_account()
    fills = [s for s in steps if s.executed]
    blocks = [s for s in steps if s.blocked]
    lines = []
    lines.append("=" * 72)
    lines.append("BACKTEST REPORT")
    lines.append("=" * 72)
    for s in steps:
        tag = "FILL" if s.executed else ("BLOCK" if s.blocked else s.state.value.upper())
        px = f" @ {s.fill_price:g}" if s.fill_price is not None else ""
        lines.append(f"[{tag:>6}] {s.command}{px}")
        if s.message and (s.executed is False):
            lines.append(f"          -> {s.message}")
    lines.append("-" * 72)
    lines.append(f"Commands: {len(steps)}   Fills: {len(fills)}   Blocked: {len(blocks)}")
    lines.append(f"Realized P&L (today): ${acct.realized_pnl_today:,.2f}")
    lines.append(f"Cash: ${acct.buying_power:,.2f}")
    equity = acct.buying_power + sum(p.market_value for p in acct.positions)
    lines.append(f"Equity: ${equity:,.2f}")
    pos = ", ".join(f"{p.symbol}={p.quantity:g}" for p in acct.positions) or "(none)"
    lines.append(f"Positions: {pos}")
    lines.append("=" * 72)
    return "\n".join(lines)
