"""Expiry-shorthand parsing for options.

Expressions like "this Friday", "next Friday", "0DTE", "today", "Nov 20" are
resolved to concrete ISO dates. `today` is injectable so the parser is fully
deterministic and testable.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
}

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_MONTH_DAY_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")


def next_weekday(today: date, weekday: int) -> date:
    """Next occurrence of `weekday` at or after `today`."""
    days_ahead = (weekday - today.weekday()) % 7
    return today + timedelta(days=days_ahead)


def resolve_expiry(label: str, today: date) -> date | None:
    """Resolve a canonical expiry label to a date. Returns None if unknown."""
    label = label.strip().lower()

    if label in ("0dte", "0 dte", "zero dte", "today", "today's", "todays"):
        return today

    if label == "this week":
        return next_weekday(today, 4)
    if label == "next week":
        return next_weekday(today, 4) + timedelta(days=7)
    if label == "this month":
        return _monthly_expiry(today)
    if label == "next month":
        return _monthly_expiry(_next_month(today))

    for w, num in WEEKDAYS.items():
        if label == w:
            return next_weekday(today, num)
        if label == f"this {w}":
            return next_weekday(today, num)
        if label == f"next {w}":
            return next_weekday(today, num) + timedelta(days=7)

    m = _MONTH_DAY_RE.match(label)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        return _month_day_date(today, month, day)

    for name, num in MONTHS.items():
        if label.startswith(name):
            rest = label[len(name):].strip().rstrip("thstndrd")
            if rest.isdigit():
                return _month_day_date(today, num, int(rest))

    return None


def _month_day_date(today: date, month: int, day: int) -> date | None:
    try:
        d = date(today.year, month, day)
    except ValueError:
        return None
    if d < today:
        d = date(today.year + 1, month, day)
    return d


def _next_month(today: date) -> date:
    if today.month == 12:
        return date(today.year + 1, 1, 1)
    return date(today.year, today.month + 1, 1)


def _monthly_expiry(today: date) -> date:
    """Third Friday of the current month (standard monthly options expiry)."""
    first = date(today.year, today.month, 1)
    return next_weekday(first, 4) + timedelta(days=14)


def days_to_expiry(iso: str | date, today: date) -> int:
    d = iso if isinstance(iso, date) else date.fromisoformat(iso)
    return (d - today).days
