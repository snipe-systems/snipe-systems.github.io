"""Confirmation gate.

The gate is deliberately strict: the ONLY thing that advances a pending order
to execution is an utterance containing the word "confirm" (and not a
negation). "Yeah", silence, or anything ambiguous keeps the order pending.
"cancel"/"stop"/"no" cancels it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from ..parser.intent import Command


NEGATIONS = {
    "cancel", "stop", "no", "not", "dont", "don't", "never", "nah", "nope",
    "negative", "abort", "hold", "wait", "nevermind",
}

_WORD_RE = re.compile(r"[a-z']+")


@dataclass
class PendingOrder:
    command: Command
    description: str
    quoted_price: float | None
    idempotency_key: str
    created_at: float = field(default_factory=time.time)

    def age(self) -> float:
        return time.time() - self.created_at


class ConfirmationGate:
    def __init__(self):
        self.pending: PendingOrder | None = None

    def begin(self, command: Command, description: str,
              quoted_price: float | None, idempotency_key: str) -> None:
        self.pending = PendingOrder(
            command=command,
            description=description,
            quoted_price=quoted_price,
            idempotency_key=idempotency_key,
        )

    def is_pending(self) -> bool:
        return self.pending is not None

    def interpret(self, text: str) -> str:
        """Return 'confirmed', 'cancelled', or 'pending'.

        Only a whole word "confirm" (with no negation word present) advances the
        order. "yeah", silence, or anything ambiguous keeps it pending.
        "disconfirm"/"unconfirmed" do NOT count, and "confirm now" DOES count.
        """
        if self.pending is None:
            return "noop"
        tokens = set(_WORD_RE.findall(text.lower()))
        has_negation = bool(tokens & NEGATIONS)
        has_confirm = "confirm" in tokens
        if has_confirm and not has_negation:
            return "confirmed"
        if has_negation:
            self.pending = None
            return "cancelled"
        return "pending"

    def clear(self) -> None:
        self.pending = None
