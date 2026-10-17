"""Stress test: 20+ tricky commands. Pass bar = ZERO wrong executions.

Runnable standalone:

    python tests/stress_test.py

or as a pytest. A "wrong execution" is defined as a fill that should not have
happened (ambiguous, low-information, blocked, or a command spoken while another
is still confirming). The script prints a pass/fail table and exits non-zero on
any wrong execution.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voice_trader.core.session import TradingSession  # noqa: E402
from voice_trader.core.journal import Journal  # noqa: E402
from voice_trader.core.killswitch import KillSwitch  # noqa: E402
from voice_trader.risk.engine import RiskConfig, RiskEngine  # noqa: E402
from voice_trader.parser.resolver import Resolver  # noqa: E402
from voice_trader.parser.parser import parse  # noqa: E402
from voice_trader.broker.paper_broker import PaperBroker  # noqa: E402


class _Null:
    def __getattr__(self, _n):
        return lambda *a, **k: None


def _session(tmp=None):
    tmp = Path(tmp) if tmp else Path(tempfile.mkdtemp(prefix="voice-trader-stress-"))
    tmp.mkdir(parents=True, exist_ok=True)
    broker = PaperBroker(market_open=True)
    broker._positions["TSLA"] = {"qty": 20.0, "avg": 280.0, "last": 300.0}
    return TradingSession(
        config={"voice_auth": {"required": False}},
        broker=broker,
        risk=RiskEngine(RiskConfig.from_dict({})),
        resolver=Resolver(broker.symbol_universe()),
        journal=Journal(tmp / "trades.csv"),
        killswitch=KillSwitch(tmp / "killswitch"),
        log=_Null(),
        speaker=None, voice_verifier=None, mode="paper",
    ), broker


# Number-confusion checks: (phrase, expected quantity).
NUMBER_CHECKS = [
    ("buy fifteen shares of Apple at 230", 15.0),
    ("buy fifty shares of Apple at 230", 50.0),
    ("sell fifteen percent of my Tesla position", 0.15),
    ("buy two hundred thirty shares of Tesla", 230.0),
    ("buy 5 AAPL at 230", 5.0),
    ("buy 15 AAPL at 230", 15.0),
    ("buy 50 AAPL at 230", 50.0),
]

# (command, should_execute, note)
CASES = [
    ("buy 50 SPX puts", False, "SPX vs SPY confusable ticker"),
    ("buy 10 shares of SPX", False, "SPX vs SPY confusable ticker"),
    ("buy 10 shares of SPY at 500", False, "SPY vs SPX confusable ticker"),
    ("buy shares of Apple", False, "missing quantity -> ask"),
    ("sell my Tesla position", False, "no position to close -> blocked"),
    ("buy 1000000 shares of AAPL", False, "order value exceeds limit"),
    ("close my SPY put", False, "option strike unknown -> ask"),
    ("buy 10 shares of Goog", False, "GOOG vs GOOGL confusable"),
    ("cancel all orders", False, "needs confirmation, not auto-executed"),
    ("move my stop on SPY to 760", False, "control command, no execution"),
    ("what's my delta on my SPY put", False, "query, no execution"),
    ("tag this pullback-RS", False, "tagging, no execution"),
    ("buy 10 AAPL stop at 225", False, "needs confirmation"),
    ("um yeah buy ten aapl at two hundred thirty", False, "noise but must still confirm"),
    ("sell all my Tesla position", True, "clear close of existing position"),
    ("buy 5 SPY 770 puts expiring this Friday", False, "options order needs confirm"),
    ("stop trading", False, "halts, no execution"),
    ("flatten everything", False, "needs confirmation"),
]


def run_stress(verbose: bool = True) -> tuple[bool, list[dict]]:
    results: list[dict] = []
    wrong = 0

    # 1. Number-confusion checks (parse accuracy).
    for phrase, expected in NUMBER_CHECKS:
        cmd = parse(phrase)
        actual = cmd.order.quantity if cmd.order else None
        ok = actual == expected
        if not ok:
            wrong += 1
        results.append({"cmd": phrase, "expect": expected, "got": actual, "ok": ok,
                        "kind": "number"})

    # 2. Individual tricky commands, each on a fresh session.
    for command, should_execute, note in CASES:
        session, broker = _session()
        r = session.handle_utterance(command, audio=None)
        executed = r.executed
        if r.pending_confirmation and should_execute:
            r2 = session.handle_utterance("confirm", audio=None)
            executed = r2.executed
        ok = (executed == should_execute)
        if not ok:
            wrong += 1
        results.append({"cmd": command, "should_execute": should_execute,
                        "executed": executed, "ok": ok, "note": note,
                        "result": r.text[:80]})

    # 3. Command spoken while another is still confirming.
    session, broker = _session()
    r1 = session.handle_utterance("buy 10 shares of Apple at 230")
    assert r1.pending_confirmation
    r2 = session.handle_utterance("buy 20 shares of Microsoft at market")
    ok = (r2.executed is False)
    if not ok:
        wrong += 1
    results.append({"cmd": "buy 20 MSFT while 'buy 10 AAPL' confirming",
                    "should_execute": False, "executed": r2.executed, "ok": ok,
                    "note": "second order during pending confirm", "result": r2.text[:80]})
    session.handle_utterance("cancel")

    # 4. Duplicate command must not double-fill.
    session, broker = _session()
    session.handle_utterance("buy 10 shares of Apple at 230")
    session.handle_utterance("confirm")
    r3 = session.handle_utterance("buy 10 shares of Apple at 230")
    acct = broker.get_account()
    aapl = [p for p in acct.positions if p.symbol == "AAPL"]
    ok = (r3.executed is False) and (len(aapl) == 1 and aapl[0].quantity == 10)
    if not ok:
        wrong += 1
    results.append({"cmd": "repeat 'buy 10 AAPL' after fill", "should_execute": False,
                    "executed": r3.executed, "ok": ok, "note": "duplicate guard",
                    "result": r3.text[:80]})

    if verbose:
        print("\nSTRESS TEST RESULTS")
        print("-" * 100)
        passed = sum(1 for x in results if x["ok"])
        for x in results:
            mark = "PASS" if x["ok"] else "FAIL"
            print(f"[{mark}] {x['cmd']!r:55} -> executed={x.get('executed', '-')}  {x.get('note','')}")
        print("-" * 100)
        print(f"{passed}/{len(results)} passed. Wrong executions: {wrong}")
        print("PASS BAR: zero wrong executions." + ("" if wrong == 0 else " FAILED."))

    return wrong == 0, results


def test_stress_zero_wrong_executions():
    ok, results = run_stress(verbose=False)
    assert ok, f"stress test failed: {[r for r in results if not r['ok']]}"


if __name__ == "__main__":
    ok, _ = run_stress()
    sys.exit(0 if ok else 1)
