"""Public Python API tests: drive the package the way external software would."""

from __future__ import annotations

import voice_trader
from voice_trader import create_session, run_command, TradingSession, Response


def test_import_surface():
    # The public surface is importable from the package root.
    for name in ["create_session", "run_command", "TradingSession", "Response",
                 "parse", "Resolver", "RiskEngine", "PaperBroker", "Journal",
                 "KillSwitch", "describe_command"]:
        assert hasattr(voice_trader, name), name


def test_programmatic_buy_confirm_fill(tmp_path):
    session = create_session(journal_path=tmp_path / "t.csv",
                             killswitch_path=tmp_path / "ks")
    r1 = run_command(session, "buy 10 shares of Apple at 230")
    assert r1.pending_confirmation

    r2 = run_command(session, "confirm")
    assert r2.executed
    assert "Filled" in r2.text

    # Journal was written and is readable by external tools.
    rows = session.journal.read()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert float(rows[0]["quantity"]) == 10.0


def test_programmatic_seed_position_and_reduce(tmp_path):
    session = create_session(seed_positions={"TSLA": 20.0}, prices={"TSLA": 300.0},
                             journal_path=tmp_path / "t.csv",
                             killswitch_path=tmp_path / "ks")
    run_command(session, "sell half my Tesla position")
    r = run_command(session, "confirm")
    assert r.executed
    pos = {p.symbol: p.quantity for p in session.broker.get_account().positions}
    assert pos["TSLA"] == 10.0


def test_public_api_never_auto_executes(tmp_path):
    session = create_session(journal_path=tmp_path / "t.csv",
                             killswitch_path=tmp_path / "ks")
    # No confirm -> nothing executes even after a perfectly valid order.
    run_command(session, "buy 10 shares of Apple at 230")
    assert session.broker.get_account().positions == []
