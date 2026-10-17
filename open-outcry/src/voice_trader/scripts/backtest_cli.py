"""Backtest CLI.

    voice-trader-backtest                     # jump scenario (stale-price demo)
    voice-trader-backtest --scenario random   # random-walk, longer script
    voice-trader-backtest --script cmds.txt   # your own command script
"""

from __future__ import annotations

import argparse
import sys

from ..backtest.price_feed import PriceFeed, jump, random_walk
from ..backtest.replay_broker import ReplayBroker
from ..backtest.runner import build_session, report, run_script

JUMP_SCRIPT = [
    "buy 10 AAPL at market",     # read-back quotes 230
                                 # confirm -> price jumps to 300 -> re-confirm
    "buy 10 AAPL at market",     # duplicate guard should block this repeat
    "buy 10 MSFT at 250",        # limit above market -> fills
    "buy 10 MSFT at 200",        # limit below market -> rejected (not marketable)
    "flatten everything",
]

RANDOM_SCRIPT = [
    "buy 10 AAPL at market",
    "buy 5 TSLA at 300",
    "sell half my Apple position",
    "buy 100000 shares of AAPL at 230",
    "what's my delta",
    "flatten everything",
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="voice-trader-backtest")
    p.add_argument("--scenario", choices=["jump", "random"], default="jump")
    p.add_argument("--script", default=None, help="file of commands, one per line")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--journal", default=None,
                   help="journal output path (default: temporary)")
    args = p.parse_args(argv)

    if args.scenario == "jump":
        feed = PriceFeed({
            "AAPL": [230.0, 230.0, 300.0, 300.0],
            "MSFT": [240.0, 240.0],
        })
        script = JUMP_SCRIPT
    else:
        feed = random_walk(["AAPL", "TSLA"], n=300, start=230.0, seed=args.seed)
        script = RANDOM_SCRIPT

    if args.script:
        with open(args.script) as f:
            script = [ln.strip() for ln in f if ln.strip()]

    broker = ReplayBroker(feed)
    session = build_session(broker, journal_path=args.journal)
    steps = run_script(session, script)
    print(report(steps, broker))
    return 0


if __name__ == "__main__":
    sys.exit(main())
