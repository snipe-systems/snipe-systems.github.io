"""Deterministic, rule-based natural-language parser.

No LLM sits in the execution path. The parser extracts a structured Command
with per-field confidence scores. Anything it cannot confidently determine is
left blank / low-confidence so the caller MUST ask, never guess.
"""

from __future__ import annotations

import re
from datetime import date

from .intent import (
    Action,
    AssetClass,
    Command,
    CommandKind,
    OptionLeg,
    OptionType,
    OrderIntent,
    OrderType,
    QuantityKind,
)
from .numbers import parse_fraction_word, parse_number, number_words
from .options_lang import MONTHS, resolve_expiry
from .symbols import KNOWN_NAMES, TICKER_STOPWORDS

_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")

# Phrases that signal a crypto asset.
_CRYPTO_NAMES = {
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH",
    "solana": "SOL", "sol": "SOL",
    "ripple": "XRP", "xrp": "XRP",
}

_PUNCT = ".,;:!?()[]{}\"'$"


def parse(text: str, today: date | None = None) -> Command:
    today = today or date.today()
    raw = text.strip()
    low = raw.lower()

    if not raw:
        return Command(CommandKind.UNKNOWN, raw, notes=["empty"])

    # --- Control / emergency commands first (highest priority) ---
    if _has_phrase(low, ["stop trading", "halt trading", "kill switch", "stop all trading", "shut it down"]):
        return Command(CommandKind.STOP_TRADING, raw, confidence={"control": 1.0})

    if _has_phrase(low, ["flatten", "close everything", "sell everything", "liquidate",
                         "close all positions", "close all my positions", "sell all positions"]):
        return Command(CommandKind.FLATTEN, raw, confidence={"control": 1.0})

    if _has_phrase(low, ["cancel all orders", "cancel all open orders", "cancel all my open orders",
                         "cancel everything", "cancel orders", "cancel all"]):
        return Command(CommandKind.CANCEL_ORDERS, raw, confidence={"control": 1.0})

    if low.strip() in ("help", "what can you do", "commands", "menu"):
        return Command(CommandKind.HELP, raw, confidence={"control": 1.0})

    if low.startswith("tag ") or low.startswith("tag this "):
        tag = raw[raw.lower().find("tag") + 3:].strip()
        tag = tag.removeprefix("this").strip().strip('"\'')
        return Command(CommandKind.TAG, raw, tag=tag, confidence={"control": 1.0})

    if "delta" in _tokens(low):
        sym = _find_symbol(raw, low)
        return Command(
            CommandKind.QUERY, raw, query_topic="delta", query_symbol=sym[0],
            confidence={"control": 1.0, "symbol": sym[1]},
        )

    if "move" in _tokens(low) and ("stop" in _tokens(low) or "stop loss" in low):
        return _parse_move_stop(raw, low)

    if ("position" in _tokens(low) or "positions" in _tokens(low)) and \
            any(w in _tokens(low) for w in ("what", "what's", "whats", "show")):
        sym = _find_symbol(raw, low)
        return Command(
            CommandKind.QUERY, raw, query_topic="position", query_symbol=sym[0],
            confidence={"control": 1.0, "symbol": sym[1]},
        )

    # --- Order / close ---
    return _parse_order(raw, low, today)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokens(low: str) -> list[str]:
    return [t.strip(_PUNCT) for t in low.split() if t.strip(_PUNCT)]


def _has_phrase(low: str, phrases: list[str]) -> bool:
    return any(p in low for p in phrases)


def _find_symbol(raw: str, low: str) -> tuple[str | None, float]:
    """Find a ticker token or company name. Returns (symbol, confidence)."""
    # Multi-word company names, longest first.
    for name in sorted(KNOWN_NAMES, key=len, reverse=True):
        if name in low:
            return KNOWN_NAMES[name], 0.9
    for name in sorted(_CRYPTO_NAMES, key=len, reverse=True):
        if name in low:
            return _CRYPTO_NAMES[name], 0.9

    # Uppercase ticker tokens.
    for tok in raw.split():
        clean = tok.strip(".,;:()[]{}\"'$")
        if _TICKER_RE.match(clean) and clean.upper() not in TICKER_STOPWORDS:
            return clean.upper(), 1.0

    # Lowercase ticker-like tokens that match a known ticker.
    for tok in low.split():
        clean = tok.strip(".,;:()[]{}\"'$")
        up = clean.upper()
        if up in KNOWN_NAMES.values() or up in _CRYPTO_NAMES.values():
            return up, 0.85
    return None, 0.0


def _parse_move_stop(raw: str, low: str) -> Command:
    sym, sym_conf = _find_symbol(raw, low)
    toks = _tokens(low)
    price = None
    price_conf = 0.0
    for i, t in enumerate(toks):
        if t == "to":
            price, _ = parse_number(toks, i + 1)
            price_conf = 1.0 if price is not None else 0.0
    order = OrderIntent(
        action=Action.CLOSE, symbol=sym, stop_price=price,
        confidence={"symbol": sym_conf, "stop_price": price_conf},
    )
    return Command(CommandKind.MOVE_STOP, raw, order=order,
                   confidence={"symbol": sym_conf, "stop_price": price_conf})


def _parse_order(raw: str, low: str, today: date) -> Command:
    toks = _tokens(low)

    # --- verb ---
    action = Action.BUY
    if "sell" in toks:
        action = Action.SELL
    elif "close" in toks:
        action = Action.CLOSE

    is_close = (action == Action.CLOSE or "position" in toks
                or (action == Action.SELL and "my" in toks)
                or _has_phrase(low, ["sell half", "sell all", "close half", "close all"]))

    # --- option detection ---
    is_option = any(w in toks for w in ("call", "calls", "put", "puts", "spread")) \
        or "dte" in low or _has_phrase(low, ["expiring", "expiry", "expires", "strike"])

    # --- symbol ---
    sym, sym_conf = _find_symbol(raw, low)

    # --- quantity ---
    qty, qty_kind, qty_conf = _parse_quantity(toks)
    # Closing (or "sell my X") with no explicit quantity -> the whole position.
    if qty_kind == QuantityKind.ABSOLUTE and qty is None and is_close:
        qty_kind = QuantityKind.ALL
        qty_conf = 0.9

    # --- prices ---
    limit, stop, target = _parse_prices(toks)

    # --- options specifics ---
    opt_leg = None
    spread = None
    if is_option:
        opt_type = OptionType.PUT if ("put" in toks or "puts" in toks) else \
                   (OptionType.CALL if ("call" in toks or "calls" in toks) else None)
        strikes = _parse_strikes(toks)
        expiry_iso, expiry_label = _parse_expiry_from_tokens(raw, low, today)

        if "spread" in toks and len(strikes) >= 2:
            legs = [OptionLeg(underlying=sym or "", option_type=opt_type,
                              strike=s, expiry=expiry_iso, expiry_label=expiry_label,
                              action=action, confidence=1.0)
                    for s in strikes]
            spread = legs
            # A spread with no explicit quantity is conventionally one spread.
            if qty_kind == QuantityKind.ABSOLUTE and qty is None:
                qty, qty_conf = 1.0, 0.8
        else:
            strike = strikes[0] if strikes else None
            opt_leg = OptionLeg(underlying=sym or "", option_type=opt_type,
                                strike=strike, expiry=expiry_iso,
                                expiry_label=expiry_label, action=action,
                                confidence=1.0 if strike is not None else 0.4)

    # --- order type + bracket ---
    bracket = stop is not None and target is not None
    if bracket:
        otype = OrderType.LIMIT if limit is not None else OrderType.MARKET
    elif stop is not None and limit is not None:
        otype = OrderType.STOP_LIMIT
    elif stop is not None:
        otype = OrderType.STOP
    elif limit is not None:
        otype = OrderType.LIMIT
    else:
        otype = OrderType.MARKET

    asset = AssetClass.OPTION if is_option else (AssetClass.CRYPTO if sym in _CRYPTO_NAMES.values() else AssetClass.STOCK)

    order = OrderIntent(
        action=action,
        symbol=sym,
        asset_class=asset,
        quantity=qty,
        quantity_kind=qty_kind,
        order_type=otype,
        limit_price=limit,
        stop_price=stop,
        target_price=target,
        option_leg=opt_leg,
        spread=spread,
        bracket=bracket,
        confidence={
            "symbol": sym_conf,
            "quantity": qty_conf,
            "order_type": 0.8,
        },
    )

    kind = CommandKind.CLOSE if (is_close and qty_kind in (QuantityKind.PERCENT, QuantityKind.ALL)) or action == Action.CLOSE else CommandKind.ORDER
    return Command(kind, raw, order=order, confidence=dict(order.confidence))


_NUM_WORDS = number_words() | {"and", "point"}


def _is_num_token(t: str) -> bool:
    return t in _NUM_WORDS or _DIGITISH.match(t) is not None


_DIGITISH = re.compile(r"^\d+(\.\d+)?$|^\.\d+$")


def _number_phrase_start(toks: list[str], end: int) -> int:
    """Start index of a contiguous numeric phrase ending just before `end`."""
    i = end - 1
    while i >= 0 and _is_num_token(toks[i]):
        i -= 1
    return i + 1


def _parse_quantity(toks: list[str]) -> tuple[float | None, QuantityKind, float]:
    """Extract quantity and its kind from tokens."""
    # "all" / "everything" -> entire position
    for t in toks:
        if t in ("all", "everything"):
            return None, QuantityKind.ALL, 1.0

    # fraction words: half, quarter, third, ...
    for t in toks:
        frac = parse_fraction_word(t)
        if frac is not None:
            return frac, QuantityKind.PERCENT, 1.0

    # "N percent" -> fraction of position
    for i, t in enumerate(toks):
        if t == "percent" and i > 0:
            start = _number_phrase_start(toks, i)
            val, consumed = parse_number(toks, start)
            if val is not None and start + consumed == i:
                return val / 100.0, QuantityKind.PERCENT, 1.0

    # number phrase followed by shares/contracts/share/contract
    for i, t in enumerate(toks):
        if t in ("shares", "share", "contracts", "contract", "contract"):
            start = _number_phrase_start(toks, i)
            val, consumed = parse_number(toks, start)
            if val is not None and start + consumed == i:
                return val, QuantityKind.ABSOLUTE, 1.0

    # leading bare number (first numeric token not clearly a price/strike/expiry)
    for i, t in enumerate(toks):
        val, n = parse_number(toks, i)
        if val is not None and n > 0:
            # avoid mistaking a price as quantity
            if i > 0 and toks[i - 1] in ("at", "limit", "stop", "target"):
                continue
            # avoid mistaking an option strike or expiry day as quantity
            if _is_strike_or_expiry(toks, i):
                continue
            return val, QuantityKind.ABSOLUTE, 0.85

    return None, QuantityKind.ABSOLUTE, 0.0


def _is_strike_or_expiry(toks: list[str], i: int) -> bool:
    """A number is not a quantity if it sits before put/call (option strike)
    or after a month name (expiry day)."""
    nxt = toks[i + 1] if i + 1 < len(toks) else ""
    prev = toks[i - 1] if i > 0 else ""
    if nxt in ("put", "puts", "call", "calls", "spread"):
        return True
    if prev in MONTHS:
        return True
    return False


def _parse_prices(toks: list[str]) -> tuple[float | None, float | None, float | None]:
    """Extract raw limit/stop/target numbers. Order-type and bracket logic
    lives in `_parse_order`."""
    limit = stop = target = None
    n = len(toks)
    i = 0
    while i < n:
        t = toks[i]
        if t == "at":
            if i > 0 and toks[i - 1] == "stop":
                i += 1
                continue
            val, _ = parse_number(toks, i + 1)
            if val is not None:
                limit = val
        elif t == "limit":
            val, _ = parse_number(toks, i + 1)
            if val is not None:
                limit = val
        elif t == "stop":
            if i + 1 < n and toks[i + 1] == "at":
                val, _ = parse_number(toks, i + 2)
            else:
                val, _ = parse_number(toks, i + 1)
            if val is not None:
                stop = val
        elif t == "target":
            val, _ = parse_number(toks, i + 1)
            if val is not None:
                target = val
        i += 1
    return limit, stop, target


def _parse_strikes(toks: list[str]) -> list[float]:
    """Find option strike prices. Handles '770 puts' and '760/770' slash forms."""
    strikes: list[float] = []

    # slash form: 760/770
    for t in toks:
        if "/" in t:
            parts = t.split("/")
            for p in parts:
                try:
                    strikes.append(float(p))
                except ValueError:
                    pass
            if strikes:
                return strikes

    # number immediately preceding put/call
    for i, t in enumerate(toks):
        if t in ("put", "puts", "call", "calls") and i > 0:
            val, _ = parse_number(toks, i - 1)
            if val is not None:
                strikes.append(val)

    return strikes


def _parse_expiry_from_tokens(raw: str, low: str, today: date) -> tuple[str | None, str | None]:
    """Resolve an expiry phrase to (iso_date, label)."""
    toks = _tokens(low)

    # "expiring this friday", "expiry nov 20", "exp this friday"
    for kw in ("expiring", "expiry", "expires", "exp"):
        if kw in toks:
            i = toks.index(kw)
            phrase = " ".join(toks[i + 1:i + 4])
            iso = resolve_expiry(phrase, today)
            if iso:
                return iso.isoformat(), phrase
            return None, phrase

    # 0DTE / ndte forms
    dte_m = re.search(r"(\d+)\s*dte", low)
    if dte_m:
        d = int(dte_m.group(1))
        return (today.fromordinal(today.toordinal() + d)).isoformat(), f"{d}dte"

    # bare weekday / month-day phrase: "this friday", "nov 20"
    for phrase_len in (3, 2):
        for i in range(len(toks)):
            phrase = " ".join(toks[i:i + phrase_len])
            iso = resolve_expiry(phrase, today)
            if iso:
                return iso.isoformat(), phrase
            # also single word weekday
            if phrase_len == 2 and resolve_expiry(toks[i], today):
                iso = resolve_expiry(toks[i], today)
                return iso.isoformat(), toks[i]

    return None, None


# ---------------------------------------------------------------------------
# Spread direction assignment (standard options convention)
# ---------------------------------------------------------------------------

def spread_to_legs(spread: list[OptionLeg], action: Action) -> list[OptionLeg]:
    """Assign long/short legs for a two-leg vertical spread using the standard
    debit-spread convention:
      - buy call spread: buy lower strike, sell higher strike
      - buy put spread:  buy higher strike, sell lower strike
    A SELL action inverts the convention (credit spread).
    """
    if len(spread) != 2:
        return spread

    legs = sorted(spread, key=lambda l: l.strike)
    low, high = legs[0], legs[1]

    if action == Action.BUY:
        if low.option_type == OptionType.CALL:
            low.action, high.action = Action.BUY, Action.SELL
        else:  # put
            low.action, high.action = Action.SELL, Action.BUY
    else:  # sell (credit spread)
        if low.option_type == OptionType.CALL:
            low.action, high.action = Action.SELL, Action.BUY
        else:
            low.action, high.action = Action.BUY, Action.SELL

    return [low, high]
