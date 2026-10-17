"""Pipeline state machine and the orchestrating TradingSession."""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    PARSING = "parsing"
    RESOLVING = "resolving"
    VALIDATING = "validating"
    CONFIRMING = "confirming"
    EXECUTING = "executing"
    REPORTING = "reporting"
    BLOCKED = "blocked"
    HALTED = "halted"
