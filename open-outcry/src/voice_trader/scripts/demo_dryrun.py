"""Scripted dry-run demo.

Runs real commands through the FULL pipeline (parse -> resolve -> validate ->
confirm -> execute) against the local paper broker and prints exactly what
WOULD happen. No order ever leaves the machine. The confirmation step is
auto-answered here only for demonstration; in live use it requires a spoken
"confirm".
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..core.config import load_config, load_env
from ..core.logging import AuditLogger
from ..core.session import TradingSession
from ..core.journal import Journal
from ..core.killswitch import KillSwitch
from ..risk.engine import RiskConfig, RiskEngine
from ..parser.resolver import Resolver
from ..broker.paper_broker import PaperBroker

DEMO_COMMANDS = [
    "buy 10 shares of Apple at 230",
    "buy 10 AAPL at 230, stop at 225, target 240",
    "sell half my Tesla position",
    "buy 5 SPY 770 puts expiring this Friday",
    "sell my QQQ 0DTE calls",
    "what's my delta",
    "cancel all orders",
    "flatten everything",
    "buy 100000 shares of AAPL at 230",
    "buy TSLA",
    "buy 50 SPX puts",
    "stop trading",
]


def run_demo() -> int:
    load_env()
    config = load_config()
    config["mode"] = "paper"
    config["active_broker"] = "paper"
    config.setdefault("voice_auth", {})["required"] = False

    broker = PaperBroker(market_open=True)
    # Seed a position so position-aware commands have something to act on.
    broker._positions["TSLA"] = {"qty": 20.0, "avg": 280.0, "last": 300.0}

    tmp = Path(tempfile.mkdtemp(prefix="voice-trader-demo-"))
    session = TradingSession(
        config=config,
        broker=broker,
        risk=RiskEngine(RiskConfig.from_dict(config.get("risk", {}))),
        resolver=Resolver(broker.symbol_universe()),
        journal=Journal(tmp / "trades.csv"),
        killswitch=KillSwitch(tmp / "killswitch"),
        log=AuditLogger(),
        speaker=None,
        voice_verifier=None,
        mode="paper",
    )

    print("\n" + "=" * 72)
    print("DRY-RUN DEMO — paper broker, no real orders. Auto-confirm for demo only.")
    print("=" * 72)

    for text in DEMO_COMMANDS:
        print(f"\n>> {text}")
        resp = session.handle_utterance(text, audio=None)
        print(f"   [{resp.state.value.upper()}] {resp.text}")
        # If a confirmation is pending, auto-confirm to show the fill path.
        while resp.pending_confirmation:
            resp = session.handle_utterance("confirm", audio=None)
            print(f"   [{resp.state.value.upper()}] {resp.text}")

    print("\n" + "=" * 72)
    print("Demo complete.")
    return 0


def main() -> int:
    return run_demo()


if __name__ == "__main__":
    raise SystemExit(main())
