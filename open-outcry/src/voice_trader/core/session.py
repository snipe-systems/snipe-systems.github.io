"""TradingSession: the orchestrator that runs the full safety pipeline.

This is the single choke point between a spoken utterance and a broker order.
Every hard safety rule lives in the path this class executes:
    parse -> resolve -> validate -> confirm -> execute -> journal
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date

from ..parser.intent import (
    AssetClass,
    Command,
    CommandKind,
    OrderIntent,
    QuantityKind,
    describe_command,
)
from ..parser.parser import parse, spread_to_legs
from ..parser.resolver import Resolver
from ..risk.engine import AccountState, RiskEngine, Violation
from ..broker.base import BrokerAdapter, BrokerError
from .confirmation import ConfirmationGate
from .events import EventBus
from .journal import Journal
from .killswitch import KillSwitch
from .logging import AuditLogger
from .state import State
from .pricing import option_delta

STOP_PHRASES = ("stop trading", "halt trading", "kill switch", "stop all trading", "shut it down")


@dataclass
class Response:
    text: str
    state: State = State.IDLE
    executed: bool = False
    blocked: bool = False
    pending_confirmation: bool = False

    def __str__(self) -> str:
        return self.text


class TradingSession:
    def __init__(self, *, config: dict, broker: BrokerAdapter, risk: RiskEngine,
                 resolver: Resolver, journal: Journal, killswitch: KillSwitch,
                 log: AuditLogger, speaker=None, voice_verifier=None,
                 mode: str = "paper", market_status_fn=None):
        self.config = config
        self.broker = broker
        self.risk = risk
        self.resolver = resolver
        self.journal = journal
        self.killswitch = killswitch
        self.log = log
        self.speaker = speaker
        self.voice_verifier = voice_verifier
        self.mode = mode
        self.gate = ConfirmationGate()
        self.halted = False
        self._market_status_fn = market_status_fn
        self.confidence_threshold = float(config.get("confidence_threshold", 0.6))
        self.events = EventBus()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Entry point: one utterance in, one response out.
    # ------------------------------------------------------------------

    def handle_utterance(self, text: str, audio=None) -> Response:
        with self._lock:
            return self._handle_utterance(text, audio)

    def _handle_utterance(self, text: str, audio=None) -> Response:
        text = (text or "").strip()
        self.log.transcript(text)
        self.events.emit({"type": "transcript", "text": text})

        if not text:
            return Response("I didn't hear anything.", State.IDLE)

        # Global voice kill switch (works even mid-confirmation).
        if any(p in text.lower() for p in STOP_PHRASES):
            self.halted = True
            self.killswitch.trigger_voice()
            self.gate.clear()
            self.log.event("halted", reason="voice")
            self.events.emit({"type": "halted", "reason": "voice"})
            self._speak("Trading halted.")
            return Response("Trading halted.", State.HALTED)

        if self.halted or self.killswitch.is_halted():
            return Response("Trading is halted. Remove the kill-switch file and restart to resume.",
                            State.HALTED)

        # Interrupt / confirm a pending order.
        if self.gate.is_pending():
            return self._handle_pending(text)

        return self._process_command(text, audio)

    # ------------------------------------------------------------------
    # Pending (confirmation) handling.
    # ------------------------------------------------------------------

    def _handle_pending(self, text: str) -> Response:
        verdict = self.gate.interpret(text)
        if verdict == "confirmed":
            return self._execute_pending()
        if verdict == "cancelled":
            self.log.event("cancelled")
            self.events.emit({"type": "cancelled"})
            self._speak("Order cancelled.")
            return Response("Order cancelled.", State.IDLE)
        self._speak("Say confirm to execute, or cancel to abort.")
        return Response("Say 'confirm' to execute, or 'cancel' to abort.",
                        State.CONFIRMING, pending_confirmation=True)

    # ------------------------------------------------------------------
    # New command.
    # ------------------------------------------------------------------

    def _process_command(self, text: str, audio=None) -> Response:
        command = parse(text)
        self.log.event("parsed", command_kind=command.kind.value, desc=describe_command(command))

        # Bare confirm/cancel with nothing pending is a friendly no-op.
        if command.kind == CommandKind.UNKNOWN and text.lower().strip() in \
                ("confirm", "cancel", "stop", "abort", "no"):
            return Response("Nothing pending to confirm or cancel.", State.IDLE)

        if command.kind == CommandKind.STOP_TRADING:
            self.halted = True
            self.killswitch.trigger_voice()
            self._speak("Trading halted.")
            return Response("Trading halted.", State.HALTED)

        if command.kind == CommandKind.HELP:
            return Response(self._help_text(), State.IDLE)

        # Speaker verification for anything that can execute.
        if command.kind in _EXECUTION_KINDS:
            refusal = self._check_voice_auth(audio)
            if refusal:
                return refusal

        if command.kind == CommandKind.QUERY:
            return self._handle_query(command)

        if command.kind == CommandKind.TAG:
            ok = self.journal.tag_last(command.tag or "")
            return Response(f"Tagged last trade: {command.tag}" if ok
                            else "No trades to tag yet.", State.IDLE)

        if command.kind == CommandKind.CANCEL_ORDERS:
            return self._cancel_all(command)

        if command.kind == CommandKind.FLATTEN:
            return self._flatten(command)

        if command.kind == CommandKind.MOVE_STOP:
            return self._move_stop(command)

        if command.kind in (CommandKind.ORDER, CommandKind.CLOSE):
            return self._order_flow(command)

        return Response("I didn't understand that. Please repeat.", State.IDLE)

    # ------------------------------------------------------------------
    # Order flow.
    # ------------------------------------------------------------------

    def _order_flow(self, command: Command) -> Response:
        o = command.order
        if o is None:
            return Response("Couldn't parse an order. Please repeat.", State.IDLE)

        # 1. Symbol resolution + ambiguity.
        if not o.symbol:
            self._speak("Which symbol?")
            return Response("I didn't catch the symbol. Which symbol?", State.RESOLVING)
        res = self.resolver.resolve(o.symbol)
        if not res.found:
            if res.ambiguity:
                cands = ", ".join(res.ambiguity)
                self._speak(f"I don't recognize {o.symbol}. Did you mean {cands}?")
                return Response(f"Symbol {o.symbol} not found. Did you mean {cands}?",
                                State.RESOLVING)
            self._speak(f"Symbol {o.symbol} not found.")
            return Response(f"Symbol {o.symbol} not found.", State.RESOLVING)
        o.symbol = res.symbol
        # Near-neighbour tickers (SPY vs SPX) are surfaced as an extra caution
        # in the confirmation read-back. Execution still requires an explicit
        # spoken "confirm", so the symbol is never silently picked.
        caution = None
        if res.ambiguity:
            caution = f"Did you mean {', '.join(res.ambiguity)}?"
            self.log.event("ambiguous", symbol=o.symbol, candidates=",".join(res.ambiguity))

        # 1b. Missing-field and option-position resolution (ask, never guess).
        if command.kind == CommandKind.ORDER and o.quantity_kind == QuantityKind.ABSOLUTE \
                and o.quantity is None:
            self._speak("How many?")
            return Response("How many shares or contracts?", State.RESOLVING)

        # Position-aware option closes: resolve the exact contract quantity from
        # the existing position and convert to an absolute quantity so the risk
        # engine and broker look up the correct (composite) position key.
        if o.asset_class == AssetClass.OPTION and o.option_leg is not None \
                and o.quantity_kind in (QuantityKind.PERCENT, QuantityKind.ALL):
            match = self._match_option_position(o)
            if match:
                strike, expiry, qty = match
                if o.option_leg.strike is None:
                    o.option_leg.strike = strike
                if o.option_leg.expiry is None:
                    o.option_leg.expiry = expiry
                o.quantity = qty if o.quantity_kind == QuantityKind.ALL else qty * (o.quantity or 0.0)
                o.quantity_kind = QuantityKind.ABSOLUTE
                command.notes.append("matched existing option position")
            elif command.kind == CommandKind.CLOSE:
                self._speak(f"Which {o.symbol} option? Tell me the strike and expiry.")
                return Response(f"Which {o.symbol} option? Specify strike and expiry.",
                                State.RESOLVING)
            else:
                self._speak("Which strike and expiry?")
                return Response("Specify the option strike and expiry.", State.RESOLVING)

        # A new (absolute-quantity) option order still needs a strike.
        if o.asset_class == AssetClass.OPTION and o.option_leg is not None \
                and o.option_leg.strike is None \
                and o.quantity_kind == QuantityKind.ABSOLUTE:
            self._speak("Which strike and expiry?")
            return Response("Specify the option strike and expiry.", State.RESOLVING)

        # 2. Quote (for notional + stale-price protection).
        quote = self.broker.get_quote(o.symbol)
        last_price = quote.last_price if quote else None
        # Option "value" is the premium: use the limit price when given, else a
        # conservative estimate so market options can never bypass value limits.
        is_option = o.asset_class == AssetClass.OPTION
        if is_option:
            risk_price = o.limit_price if o.limit_price is not None \
                else self.risk.config.option_premium_estimate
            readback_price = None
        else:
            risk_price = last_price
            readback_price = last_price

        # 3. Risk validation (pre-confirm).
        account = self._account_state()
        violations = self.risk.check(command, account, risk_price)
        if violations:
            return self._block(command, violations)

        # 4. Market session awareness.
        status = self._market_status()
        if status != "open" and self.risk.config.require_market_open:
            self._speak(f"The market is {status}. I can't execute now.")
            return Response(f"The market is {status}. Trading blocked.", State.BLOCKED, blocked=True)

        # 5. Normalize quantity for the read-back (position-aware, stocks).
        if o.asset_class != AssetClass.OPTION and o.quantity_kind in ("percent", "all"):
            qty = self._position_quantity(o)
            if qty <= 0:
                return self._block(command, [Violation("no_position",
                                                       f"No position in {o.symbol} to close.")])

        # 6. Confirmation gate: read back + require explicit "confirm".
        idem = self.risk.order_signature(command)
        description = describe_command(command)
        self.gate.begin(command, description, readback_price, idem)
        self.log.event("pending_confirmation", desc=description, idem=idem,
                       price=readback_price)
        self.events.emit({"type": "pending", "description": description,
                          "idem": idem, "price": readback_price})
        readback = self._build_readback(description, readback_price, status, caution)
        self._speak(readback)
        return Response(readback, State.CONFIRMING, pending_confirmation=True)

    def _build_readback(self, description: str, price: float | None,
                        status: str, caution: str | None = None) -> str:
        s = f"Order: {description}."
        if price:
            s += f" Last price about {price:g}."
        if status != "open":
            s += f" Note: market is {status}."
        if caution:
            s += f" Caution: {caution}"
        s += " Say 'confirm' to execute, or 'cancel' to abort."
        return s

    def _execute_pending(self) -> Response:
        pending = self.gate.pending
        if pending is None:
            return Response("Nothing pending.", State.IDLE)
        command = pending.command

        # Stale-price re-quote protection (stocks only; option premium is fixed
        # by the limit price, which does not drift).
        fresh = self.broker.get_quote(command.order.symbol) if command.order and command.order.symbol else None
        if pending.quoted_price and fresh and fresh.last_price:
            drift = abs(fresh.last_price - pending.quoted_price) / pending.quoted_price
            if drift > self.risk.config.price_stale_tolerance_pct / 100.0:
                pending.quoted_price = fresh.last_price
                msg = (f"Price moved {drift*100:.1f}% to {fresh.last_price:g}. "
                       f"Say 'confirm' to execute at the new price, or 'cancel'.")
                self.log.event("re_confirm", old=pending.quoted_price, new=fresh.last_price)
                self._speak(msg)
                return Response(msg, State.CONFIRMING, pending_confirmation=True)

        # Re-validate immediately before execution.
        o = command.order
        is_option = o is not None and o.asset_class == AssetClass.OPTION
        if is_option:
            exec_price = o.limit_price if o.limit_price is not None \
                else self.risk.config.option_premium_estimate
        else:
            exec_price = fresh.last_price if fresh else None
        account = self._account_state()
        violations = self.risk.check(command, account, exec_price)
        if violations:
            self.gate.clear()
            return self._block(command, violations)

        if self.risk.is_duplicate(pending.idempotency_key):
            self.gate.clear()
            return self._block(command, [Violation("duplicate",
                "An identical order was already sent recently.")])

        # Control commands that went through the gate dispatch to their handlers.
        if command.kind == CommandKind.FLATTEN:
            self.risk.record(pending.idempotency_key)
            self.gate.clear()
            return self._do_flatten()
        if command.kind == CommandKind.CANCEL_ORDERS:
            self.risk.record(pending.idempotency_key)
            self.gate.clear()
            return self._do_cancel_all()

        # Execute.
        self.log.event("executing", idem=pending.idempotency_key)
        try:
            result = self.broker.submit_order(command, pending.idempotency_key)
        except BrokerError as e:
            self.gate.clear()
            self.log.event("rejected", error=str(e))
            self._speak(f"Order rejected: {e}")
            return Response(f"Order rejected: {e}", State.BLOCKED, blocked=True)

        if not result.ok:
            self.gate.clear()
            self.log.event("rejected", error=result.error)
            self._speak(f"Order rejected: {result.error}")
            return Response(f"Order rejected: {result.error}", State.BLOCKED, blocked=True)

        self.risk.record(pending.idempotency_key)
        self._record_fill(command, result)
        self.gate.clear()

        exec_ = result.execution
        msg = (f"Filled. {exec_.side} {exec_.quantity:g} {exec_.symbol} "
               f"at {exec_.price:g}.") if exec_ else "Order placed."
        self.log.event("filled", **({"price": exec_.price, "qty": exec_.quantity,
                                     "symbol": exec_.symbol} if exec_ else {}))
        self.events.emit({"type": "filled",
                          **({"symbol": exec_.symbol, "side": exec_.side,
                              "qty": exec_.quantity, "price": exec_.price}
                             if exec_ else {})})
        self._speak(msg)
        return Response(msg, State.REPORTING, executed=True)

    def _record_fill(self, command: Command, result) -> None:
        o = command.order
        exec_ = result.execution
        self.journal.log(
            symbol=o.symbol or (exec_.symbol if exec_ else ""),
            action=o.action.value,
            quantity=exec_.quantity if exec_ else (o.quantity or 0),
            fill_price=exec_.price if exec_ else 0,
            strategy=o.tag or "",
            idempotency_key=result.execution.idempotency_key if exec_ else "",
        )

    # ------------------------------------------------------------------
    # Emergency / control commands.
    # ------------------------------------------------------------------

    def _cancel_all(self, command: Command) -> Response:
        if self.risk.config.emergency_confirm:
            idem = self.risk.order_signature(command)
            self.gate.begin(command, "Cancel all open orders", None, idem)
            self._speak("Cancel all open orders? Say confirm or cancel.")
            return Response("Cancel all open orders? Say 'confirm' or 'cancel'.",
                            State.CONFIRMING, pending_confirmation=True)
        return self._do_cancel_all()

    def _do_cancel_all(self) -> Response:
        result = self.broker.cancel_all_orders()
        self.log.event("cancel_all", ok=result.ok)
        self._speak(result.message)
        return Response(result.message, State.REPORTING, executed=result.ok)

    def _flatten(self, command: Command) -> Response:
        if self.risk.config.emergency_confirm:
            idem = self.risk.order_signature(command)
            self.gate.begin(command, "Close all positions (flatten everything)", None, idem)
            self._speak("Flatten everything? Say confirm or cancel.")
            return Response("Flatten everything? Say 'confirm' or 'cancel'.",
                            State.CONFIRMING, pending_confirmation=True)
        return self._do_flatten()

    def _do_flatten(self) -> Response:
        result = self.broker.close_all_positions()
        self.log.event("flatten", ok=result.ok)
        self._speak(result.message)
        return Response(result.message, State.REPORTING, executed=result.ok)

    def _move_stop(self, command: Command) -> Response:
        o = command.order
        if not o or not o.symbol or o.stop_price is None:
            self._speak("Move stop on which symbol, to what price?")
            return Response("Specify a symbol and price, e.g. 'move my stop on SPY to 760'.")
        res = self.resolver.resolve(o.symbol)
        if not res.found:
            return Response(f"Symbol {o.symbol} not found.", State.RESOLVING)
        self.log.event("move_stop", symbol=res.symbol, price=o.stop_price)
        msg = f"Stop on {res.symbol} set to {o.stop_price:g}. (paper simulation)"
        self._speak(msg)
        return Response(msg, State.REPORTING)

    # ------------------------------------------------------------------
    # Queries.
    # ------------------------------------------------------------------

    def _handle_query(self, command: Command) -> Response:
        topic = command.query_topic
        if topic == "delta":
            return Response(self._delta_text(command), State.IDLE)
        if topic == "position":
            return Response(self._position_text(command), State.IDLE)
        return Response("I can answer: what's my delta, what are my positions.", State.IDLE)

    def _delta_text(self, command: Command) -> str:
        account = self.broker.get_account()
        sym = command.query_symbol
        total = 0.0
        lines = []
        today = date.today()
        for p in account.positions:
            if sym and p.symbol.upper() != sym.upper():
                continue
            if p.asset_class == "option":
                d = _option_position_delta(p, today)
            else:
                d = p.quantity
            total += d
            lines.append(f"{p.symbol}: {d:+.2f} delta")
        if not lines:
            return f"No positions{' in ' + sym if sym else ''}."
        return "Delta. " + " | ".join(lines) + f" | total {total:+.2f}"

    def _position_text(self, command: Command) -> str:
        account = self.broker.get_account()
        sym = command.query_symbol
        if not account.positions:
            return "No open positions."
        lines = []
        for p in account.positions:
            if sym and p.symbol.upper() != sym.upper():
                continue
            lines.append(f"{p.symbol}: {p.quantity:g} @ {p.avg_price:g}")
        return "Positions. " + "; ".join(lines) if lines else "No positions in " + (sym or "")

    # ------------------------------------------------------------------
    # Voice auth.
    # ------------------------------------------------------------------

    def _check_voice_auth(self, audio) -> Response | None:
        auth = self.config.get("voice_auth", {})
        if not auth.get("required", False):
            return None
        if self.voice_verifier is None or not self.voice_verifier.available():
            self.log.event("voice_auth", result="no_profile")
            self._speak("Voice authentication required but no profile is enrolled.")
            return Response("Voice authentication required but no profile is enrolled. "
                            "Execution refused.", State.BLOCKED, blocked=True)
        if audio is None:
            self._speak("Voice authentication required; no audio captured.")
            return Response("Voice authentication required; no audio captured.",
                            State.BLOCKED, blocked=True)
        matched, score = self.voice_verifier.verify(audio)
        self.log.event("voice_auth", matched=matched, score=round(score, 3))
        if not matched:
            self._speak("Speaker does not match the enrolled voice. Execution refused.")
            return Response("Speaker does not match the enrolled voice. Execution refused.",
                            State.BLOCKED, blocked=True)
        return None

    # ------------------------------------------------------------------
    # Helpers.
    # ------------------------------------------------------------------

    def _account_state(self) -> AccountState:
        acct = self.broker.get_account()
        today_str = time.strftime("%Y-%m-%d")
        trades_today = sum(1 for r in self.journal.read()
                           if r.get("timestamp", "").startswith(today_str))
        return AccountState(
            buying_power=acct.buying_power,
            positions=acct.positions,
            realized_pnl_today=acct.realized_pnl_today,
            trades_today=max(trades_today, acct.trades_today),
            open_orders=acct.open_orders,
        )

    def _position_quantity(self, o: OrderIntent) -> float:
        account = self.broker.get_account()
        for p in account.positions:
            if p.symbol.upper() == (o.symbol or "").upper():
                if o.quantity_kind == "all":
                    return abs(p.quantity)
                return abs(p.quantity) * (o.quantity or 0.0)
        return 0.0

    def _match_option_position(self, o: OrderIntent) -> tuple[float, str, float] | None:
        """Find (strike, expiry, quantity) of an existing option position
        matching the underlying + type (and strike when specified). Returns None
        when there is no unique match (caller must ask)."""
        account = self.broker.get_account()
        leg = o.option_leg
        if leg is None:
            return None
        matches: list[tuple[float, str, float]] = []
        for p in account.positions:
            if p.asset_class != "option":
                continue
            # Paper broker keys options as "SPY|put|770|2026-11-20".
            parts = p.symbol.split("|")
            if len(parts) < 3:
                continue
            if parts[0].upper() != (o.symbol or "").upper():
                continue
            if parts[1] != leg.option_type.value:
                continue
            try:
                strike = float(parts[2])
            except ValueError:
                continue
            if leg.strike is not None and abs(strike - leg.strike) > 1e-6:
                continue
            expiry = parts[3] if len(parts) > 3 else ""
            matches.append((strike, expiry, abs(p.quantity)))
        if len(matches) == 1:
            return matches[0]
        return None

    def _market_status(self) -> str:
        if self._market_status_fn:
            return self._market_status_fn()
        try:
            return self.broker.market_status()
        except BrokerError:
            return "unknown"

    def _block(self, command: Command, violations: list[Violation]) -> Response:
        reasons = "; ".join(str(v) for v in violations)
        self.log.event("blocked", reasons=reasons)
        self.events.emit({"type": "blocked", "reasons": reasons})
        self._speak(f"Blocked: {reasons}")
        return Response(f"Blocked: {reasons}", State.BLOCKED, blocked=True)

    def _speak(self, text: str) -> None:
        if self.speaker:
            self.speaker.speak(text)

    @staticmethod
    def _help_text() -> str:
        return ("Commands: buy/sell <qty> <symbol> [at <price>] [stop <p>] [target <p>] | "
                "close/flatten | cancel all orders | what's my delta/position | "
                "move my stop on <sym> to <price> | tag <strategy> | stop trading.")


_EXECUTION_KINDS = {CommandKind.ORDER, CommandKind.CLOSE, CommandKind.FLATTEN,
                    CommandKind.CANCEL_ORDERS, CommandKind.MOVE_STOP}


def _option_position_delta(p, today: date) -> float:
    """Approximate delta for an option position using Black-Scholes."""
    import math
    # Position symbol encodes something like 'SPY|put|770|2026-11-20'.
    parts = p.symbol.split("|")
    if len(parts) < 3:
        return 0.0
    underlying, opt_type, strike = parts[0], parts[1], parts[2]
    expiry = parts[3] if len(parts) > 3 else None
    try:
        S = p.last_price or p.avg_price
        K = float(strike)
    except (ValueError, TypeError):
        return 0.0
    try:
        from datetime import date as _date
        T_years = max((_date.fromisoformat(expiry) - today).days, 0) / 365.0
    except (ValueError, TypeError):
        T_years = 0.1
    d = option_delta(S, K, T_years, opt_type)
    return d * abs(p.quantity) * 100
