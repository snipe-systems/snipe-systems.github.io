"""Parsing of spoken and written numbers into floats.

This is a safety-critical piece: "fifteen" must never become 50, and "fifty"
must never become 15. The dictionary below is exhaustive for the range we
support and is covered by stress tests.
"""

from __future__ import annotations

import re

_DIGIT_RE = re.compile(r"^\d+(\.\d+)?$|^\.\d+$")

_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}

_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}

_SCALES = {
    "hundred": 100,
    "thousand": 1000,
    "million": 1_000_000,
}

_FRACTIONS = {
    "half": 0.5,
    "quarter": 0.25,
    "third": 1.0 / 3.0,
    "tenth": 0.1,
    "eighth": 0.125,
}


def _looks_like_digit(tok: str) -> bool:
    return bool(_DIGIT_RE.match(tok))


def parse_number(tokens: list[str], i: int = 0) -> tuple[float | None, int]:
    """Parse a number phrase starting at tokens[i].

    Returns (value, tokens_consumed). value is None if no number found.
    Handles: "15", "230.5", ".5", "fifteen", "fifty", "two hundred thirty",
    "two point five".
    """
    n = len(tokens)
    if i >= n:
        return None, 0

    tok = tokens[i]

    # Plain digit form, optionally with commas stripped.
    if _looks_like_digit(tok.replace(",", "")):
        return float(tok.replace(",", "")), 1

    # Word form.
    total = 0.0
    current = 0
    consumed = 0
    saw_scale = False
    j = i
    while j < n:
        w = tokens[j]
        if w in _ONES:
            current += _ONES[w]
            consumed += 1
            j += 1
            continue
        if w in _TENS:
            current += _TENS[w]
            consumed += 1
            j += 1
            continue
        if w in _SCALES:
            scale = _SCALES[w]
            if current == 0:
                current = 1
            total += current * scale
            current = 0
            saw_scale = True
            consumed += 1
            j += 1
            continue
        if w == "and":
            consumed += 1
            j += 1
            continue
        if w == "point":
            # Decimal fraction follows: "two point five"
            consumed += 1
            j += 1
            frac = 0.0
            place = 0.1
            digits = 0
            while j < n and tokens[j] in _ONES and _ONES[tokens[j]] < 10:
                frac += _ONES[tokens[j]] * place
                place /= 10.0
                digits += 1
                consumed += 1
                j += 1
            if digits == 0:
                return None, 0
            value = total + current
            return value + frac, consumed
        break

    if consumed == 0:
        return None, 0

    value = total + current
    if not saw_scale and current == 0:
        return None, 0
    return value, consumed


def parse_fraction_word(tok: str) -> float | None:
    return _FRACTIONS.get(tok)


def number_words() -> set[str]:
    return set(_ONES) | set(_TENS) | set(_SCALES)
