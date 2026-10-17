"""Confirmation gate tests: only explicit 'confirm' advances the order."""

from __future__ import annotations

from voice_trader.core.confirmation import ConfirmationGate
from voice_trader.parser.parser import parse


def _begin(gate):
    cmd = parse("buy 10 shares of Apple at 230")
    gate.begin(cmd, "buy 10 AAPL", 230.0, "abc123")


def test_confirm_advances():
    g = ConfirmationGate()
    _begin(g)
    assert g.interpret("confirm") == "confirmed"


def test_yeah_does_not_advance():
    g = ConfirmationGate()
    _begin(g)
    assert g.interpret("yeah") == "pending"
    assert g.is_pending()


def test_silence_does_not_advance():
    g = ConfirmationGate()
    _begin(g)
    assert g.interpret("") == "pending"
    assert g.is_pending()


def test_cancel_aborts():
    g = ConfirmationGate()
    _begin(g)
    assert g.interpret("cancel") == "cancelled"
    assert not g.is_pending()


def test_stop_aborts():
    g = ConfirmationGate()
    _begin(g)
    assert g.interpret("stop") == "cancelled"


def test_negation_in_confirm():
    g = ConfirmationGate()
    _begin(g)
    assert g.interpret("no don't confirm") == "cancelled"


def test_confirm_with_noise_is_fine():
    g = ConfirmationGate()
    _begin(g)
    assert g.interpret("confirm please") == "confirmed"
