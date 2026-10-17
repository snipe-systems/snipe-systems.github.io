"""End-to-end session tests: full pipeline against the paper broker."""

from __future__ import annotations

from voice_trader.core.state import State


def test_order_requires_confirm_then_fills(session_factory):
    session, broker = session_factory()
    r1 = session.handle_utterance("buy 10 shares of Apple at 230")
    assert r1.pending_confirmation is True
    assert r1.executed is False

    r2 = session.handle_utterance("yeah")
    assert r2.executed is False  # "yeah" is not a confirm

    r3 = session.handle_utterance("confirm")
    assert r3.executed is True
    assert r3.state == State.REPORTING

    acct = broker.get_account()
    assert any(p.symbol == "AAPL" and p.quantity == 10 for p in acct.positions)


def test_sell_half_position(session_factory):
    session, broker = session_factory(
        positions={"TSLA": {"qty": 20.0, "avg": 280.0, "last": 300.0}},
    )
    session.handle_utterance("sell half my Tesla position")
    r = session.handle_utterance("confirm")
    assert r.executed is True
    acct = broker.get_account()
    tsla = [p for p in acct.positions if p.symbol == "TSLA"]
    assert len(tsla) == 1 and tsla[0].quantity == 10.0


def test_ambiguous_symbol_gets_caution_but_not_executed(session_factory):
    session, broker = session_factory()
    r = session.handle_utterance("buy 1 SPY at 500")
    # SPY/SPX are known confusables -> caution in read-back, still needs confirm.
    assert r.executed is False
    assert r.pending_confirmation is True
    assert "Did you mean" in r.text
    assert broker.get_account().positions == []


def test_risk_limit_blocks(session_factory):
    session, broker = session_factory(risk=__import__("tests.conftest", fromlist=["make_risk"]).make_risk(
        max_order_value=1000.0))
    r = session.handle_utterance("buy 100 shares of Apple at 230")
    assert r.blocked is True
    assert r.executed is False


def test_kill_switch_file_halts(session_factory, tmp_path):
    session, broker = session_factory()
    session.killswitch.raise_file()
    r = session.handle_utterance("buy 10 shares of Apple at 230")
    assert r.state == State.HALTED
    assert r.executed is False


def test_stop_trading_voice_halts(session_factory):
    session, broker = session_factory()
    session.handle_utterance("buy 10 shares of Apple at 230")
    r = session.handle_utterance("stop trading")
    assert r.state == State.HALTED
    assert session.halted is True


def test_command_while_confirming_does_not_execute(session_factory):
    session, broker = session_factory()
    r1 = session.handle_utterance("buy 10 shares of Apple at 230")
    assert r1.pending_confirmation

    # A second order while the first is confirming must NOT execute.
    r2 = session.handle_utterance("buy 20 shares of Microsoft at market")
    assert r2.executed is False
    assert r2.pending_confirmation is True  # still asking for the first order

    # Cancel everything.
    r3 = session.handle_utterance("cancel")
    assert not session.gate.is_pending()
    assert broker.get_account().positions == []


def test_duplicate_order_blocked(session_factory):
    session, broker = session_factory()
    session.handle_utterance("buy 10 shares of Apple at 230")
    session.handle_utterance("confirm")

    # Repeating the identical command must not become a second order.
    r = session.handle_utterance("buy 10 shares of Apple at 230")
    assert r.executed is False
    assert r.blocked or r.state in (State.RESOLVING, State.BLOCKED)

    acct = broker.get_account()
    aapl = [p for p in acct.positions if p.symbol == "AAPL"]
    assert len(aapl) == 1 and aapl[0].quantity == 10


def test_flatten_confirms_then_closes(session_factory):
    session, broker = session_factory(
        positions={"AAPL": {"qty": 10.0, "avg": 230.0, "last": 230.0}},
    )
    r1 = session.handle_utterance("flatten everything")
    assert r1.pending_confirmation
    r2 = session.handle_utterance("confirm")
    assert r2.executed is True
    assert broker.get_account().positions == []


def test_market_closed_blocks(session_factory):
    session, broker = session_factory(market_open=False)
    r = session.handle_utterance("buy 10 shares of Apple at 230")
    assert r.blocked is True
    assert "market is closed" in r.text
