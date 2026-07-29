"""Scalar parsers mirroring upstream's Java conversions.

Java and Python disagree about what a number literal is. Python's int() accepts
underscores, surrounding whitespace, and non-ASCII digits; float() accepts
lowercase "nan" and "infinity". Integer.parseInt and Double.parseDouble accept
none of those. Since the report carries invalid_integer and invalid_float counts
per feed, matching Java exactly is what parity levels B and C require.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

# Integer.parseInt is a signed 32-bit parse: it throws outside this range even
# though Python's int is unbounded.
INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1


@dataclass(frozen=True, slots=True)
class ParseError:
    """A failed parse. Carries no notice: the caller decides which code fires."""

    reason: str


_JAVA_INT_RE = re.compile(r"\A[+-]?[0-9]+\Z")
# BigDecimal(String) accepts an optional sign, digits with an optional decimal
# point, and an optional exponent. Unlike Double.parseDouble it rejects a type
# suffix (1f, 1d) and the NaN/Infinity spellings.
_JAVA_DECIMAL_RE = re.compile(r"\A[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
# Double.parseDouble's grammar minus the hex-float form, which no feed uses.
# The specials are case sensitive in Java: "NaN" parses, "nan" throws.
_JAVA_FLOAT_RE = re.compile(
    r"\A[+-]?(?:NaN|Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?[fFdD]?)\Z"
)
_TIME_RE = re.compile(r"\A([0-9]{1,3}):([0-9]{2}):([0-9]{2})\Z")
_HEX_RE = re.compile(r"\A[0-9a-fA-F]{6}\Z")


def parse_color(value: str) -> int | ParseError:
    """GtfsColor.fromString: exactly six characters, parsed as base 16."""
    if not _HEX_RE.match(value):
        return ParseError("color must be six hexadecimal digits")
    return int(value, 16)


def parse_date(value: str) -> tuple[int, int, int] | ParseError:
    """GtfsDate.fromString: YYYYMMDD, and a date that actually exists."""
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        return ParseError("date must have YYYYMMDD format")
    year, month, day = int(value[:4]), int(value[4:6]), int(value[6:])
    try:
        date(year, month, day)
    except ValueError:
        return ParseError("date does not exist")
    return (year, month, day)


def parse_time(value: str) -> int | ParseError:
    """GtfsTime.fromString, returning seconds since midnight.

    Hours are not capped at 23. A trip departing at 25:30:00 runs past midnight
    of its service day, which GTFS requires, so this is a duration and not a
    clock reading.
    """
    match = _TIME_RE.match(value)
    if not match:
        return ParseError("time must have HH:MM:SS format")
    hours, minutes, seconds = (int(group) for group in match.groups())
    if minutes > 59 or seconds > 59:
        return ParseError("minutes and seconds must be below 60")
    return hours * 3600 + minutes * 60 + seconds


def parse_integer(value: str) -> int | ParseError:
    if not _JAVA_INT_RE.match(value):
        return ParseError("not a Java integer literal")
    parsed = int(value)
    if not (INT32_MIN <= parsed <= INT32_MAX):
        # Integer.parseInt throws on 32-bit overflow; Python's int would not.
        return ParseError("outside signed 32-bit range")
    return parsed


def parse_float(value: str) -> float | ParseError:
    if not _JAVA_FLOAT_RE.match(value):
        return ParseError("not a Java double literal")
    # Java allows a trailing type suffix that Python's float() does not.
    return float(value.rstrip("fFdD"))


# BigDecimal keeps its scale in an int, so both the literal exponent and the
# scale it implies must fit in 32 bits or the constructor throws. Python's Decimal
# has no such limit, so "1e2147483648" parses happily here and draws invalid_float
# upstream. Measured: 1e2147483647 is accepted and 1e2147483648 is not, and
# 1e-2147483648 is rejected because its scale, not its exponent, overflows.
INT32_MIN = -2147483648
INT32_MAX = 2147483647


# Java's parseExp skips leading zeros while more than this many digits remain,
# then treats anything still longer as an overflow. Reproducing that matters
# twice over: "1e" followed by five thousand zeros is a perfectly good 1 upstream,
# and Python's int() refuses to convert a string that long at all, so calling it
# raises rather than returning a verdict.
MAX_EXPONENT_DIGITS = 10


def _parse_exponent(text: str) -> int | None:
    """BigDecimal's parseExp: the exponent, or None when it overflows a long."""
    if not text:
        return 0
    sign = -1 if text[0] == "-" else 1
    digits = text[1:] if text[0] in "+-" else text
    if not digits:
        return None
    digits = digits.lstrip("0") or "0"
    if len(digits) > MAX_EXPONENT_DIGITS:
        return None
    return sign * int(digits)


def _big_decimal_scale(value: str) -> int | None:
    """The scale BigDecimal(String) would end up with, or None if it would throw.

    Java computes scale as (fraction digits - exponent) and rejects the literal
    when either the exponent or that difference leaves int range.
    """
    mantissa, _, exponent_text = value.partition("e") if "e" in value else value.partition("E")
    exponent = _parse_exponent(exponent_text)
    if exponent is None or not (INT32_MIN <= exponent <= INT32_MAX):
        return None
    _, _, fraction = mantissa.partition(".")
    scale = len(fraction) - exponent
    if not (INT32_MIN <= scale <= INT32_MAX):
        return None
    return scale


def parse_decimal(value: str) -> Decimal | ParseError:
    """BigDecimal(String): exact decimal, no type suffix, no NaN or Infinity.

    Returns a Decimal rather than a float so that precision is preserved and a
    large value cannot overflow to infinity, and so that the scale is available
    for the invalid_currency_amount check.
    """
    if not _JAVA_DECIMAL_RE.match(value):
        return ParseError("not a Java decimal literal")
    if _big_decimal_scale(value) is None:
        return ParseError("scale or exponent outside BigDecimal's 32-bit range")
    try:
        return Decimal(value)
    except InvalidOperation:  # pragma: no cover - regex already excludes this
        return ParseError("not a Java decimal literal")
