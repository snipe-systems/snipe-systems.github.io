"""Fuzz tests: the parser and the full session must never crash, and random
utterances must never execute an order."""

from __future__ import annotations

import random

from voice_trader.parser.parser import parse
from voice_trader.parser.intent import CommandKind

VOCAB = [
    "buy", "sell", "close", "open", "shares", "share", "of", "at", "stop",
    "target", "market", "limit", "put", "puts", "call", "calls", "spread",
    "expiring", "expiry", "friday", "half", "all", "everything", "my", "the",
    "ten", "fifty", "fifteen", "twenty", "hundred", "thirty", "point", "five",
    "200", "AAPL", "SPY", "SPX", "TSLA", "QQQ", "GOOG", "GOOGL", "MSFT",
    "230", "760", "770", "0DTE", "cancel", "flatten", "position",
    "delta", "tag", "move", "this", "next", "november", "20", "half", "percent",
    "my", "position", "positions", "what's", "whats", "contracts", "option",
]


def test_parser_fuzz_never_crashes():
    rng = random.Random(0)
    for _ in range(5000):
        n = rng.randint(1, 10)
        s = " ".join(rng.choice(VOCAB) for _ in range(n))
        cmd = parse(s)
        assert cmd is not None
        assert cmd.kind in CommandKind


def test_parser_mutation_fuzz_never_crashes():
    rng = random.Random(1)
    bases = [
        "buy 10 shares of Apple at 230",
        "sell half my Tesla position",
        "buy 5 SPY 770 puts expiring this Friday",
        "buy 10 AAPL at 230, stop at 225, target 240",
    ]
    for _ in range(3000):
        base = rng.choice(bases).split()
        op = rng.randint(0, 3)
        if op == 0 and len(base) > 1:
            del base[rng.randrange(len(base))]
        elif op == 1:
            base.insert(rng.randrange(len(base) + 1), rng.choice(VOCAB))
        elif op == 2 and len(base) > 1:
            base[rng.randrange(len(base))] = rng.choice(VOCAB)
        cmd = parse(" ".join(base))
        assert cmd.kind in CommandKind


def test_random_utterances_never_execute(session_factory):
    session, broker = session_factory()
    rng = random.Random(2)
    # Note: no "confirm" in this vocabulary, so nothing can ever confirm.
    for _ in range(2000):
        n = rng.randint(1, 12)
        s = " ".join(rng.choice(VOCAB) for _ in range(n))
        r = session.handle_utterance(s, audio=None)
        assert r.executed is False


def test_garbage_never_executes(session_factory):
    session, broker = session_factory()
    rng = random.Random(3)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789 .$%/"
    for _ in range(2000):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40)))
        r = session.handle_utterance(s, audio=None)
        assert r.executed is False
