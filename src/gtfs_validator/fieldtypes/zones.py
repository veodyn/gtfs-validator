"""ZoneId.of's normalisation, so the store holds the ID the entity holds.

Upstream keeps a parsed `ZoneId`, and every notice reporting one renders
`ZoneId.getId()`. Keeping the feed's spelling instead makes two agencies in the same
zone look different: `+02:00` and `+0200` are one ZoneId, and a rule comparing the raw
strings reports a mismatch the jar does not. Measured, with the whole table oracled
from the pinned JDK 17:

    +02:00, +0200, +2, +02, +020000, +02:00:00  ->  +02:00
    +00:00, +0000, +00, -00:00, Z               ->  Z
    +02:00:30, +020030                          ->  +02:00:30
    GMT+2 -> GMT+02:00 ;  UT+2 -> UT+02:00 ;  GMT+0 -> GMT ;  UTC+0 -> UTC
    GMT0, EST5EDT, Etc/GMT+5                    ->  unchanged, they are region names
    UTC0, EST, +2:0, 02:00, america/new_york     ->  rejected

A region name is returned untouched, which is why the lookup runs first: `GMT0` is a
real tzdb name and is not `GMT` plus a zero offset.
"""

from __future__ import annotations

# ZoneId.of also accepts offset-based IDs that ZoneId.getAvailableZoneIds does not
# list. A shape-only regex is not enough: ZoneOffset.of enforces component bounds and
# a +-18:00 maximum, so "+99:00", "+18:01" and "+02:60" all throw. It is also more
# permissive on shape than a fixed two-digit regex, accepting a single-digit hour
# ("+2" -> +02:00). This reproduces ZoneOffset.of and the UTC/GMT/UT prefix handling
# in ZoneId.of exactly, and is asserted against a jar corpus in the tests.
_ASCII_DIGITS = frozenset("0123456789")
_MAX_OFFSET_HOURS = 18
_PREFIXES = ("UTC", "GMT", "UT")


def offset_seconds(text: str) -> int | None:
    """ZoneOffset.of in seconds, or None where it would throw.

    Accepted shapes are +h, +hh, +hhmm, +hh:mm, +hhmmss and +hh:mm:ss (a colon is
    only legal at the six- and nine-character lengths). Hours run 0..18, minutes and
    seconds 0..59, and 18:00:00 is the maximum, so +18:01 is rejected.

    Returning seconds rather than a bool keeps validity and normalisation as one
    parser. Two of them would be free to disagree, and only one is jar-asserted.
    """
    if text == "Z":
        return 0
    if not text or text[0] not in "+-":
        return None
    length = len(text)
    if length == 2:  # +h, normalised by Java to +0h
        digits, has_colons = text[1], False
        hours_s, minutes_s, seconds_s = text[1], "0", "0"
    elif length == 3:  # +hh
        digits, has_colons = text[1:3], False
        hours_s, minutes_s, seconds_s = text[1:3], "0", "0"
    elif length == 5:  # +hhmm
        digits, has_colons = text[1:5], False
        hours_s, minutes_s, seconds_s = text[1:3], text[3:5], "0"
    elif length == 6:  # +hh:mm
        digits, has_colons = text[1:3] + text[4:6], text[3] == ":"
        hours_s, minutes_s, seconds_s = text[1:3], text[4:6], "0"
    elif length == 7:  # +hhmmss
        digits, has_colons = text[1:7], False
        hours_s, minutes_s, seconds_s = text[1:3], text[3:5], text[5:7]
    elif length == 9:  # +hh:mm:ss
        digits, has_colons = text[1:3] + text[4:6] + text[7:9], text[3] == ":" and text[6] == ":"
        hours_s, minutes_s, seconds_s = text[1:3], text[4:6], text[7:9]
    else:
        return None
    if length in (6, 9) and not has_colons:
        return None
    if not all(character in _ASCII_DIGITS for character in digits):
        return None
    hours, minutes, seconds = int(hours_s), int(minutes_s), int(seconds_s)
    if hours > _MAX_OFFSET_HOURS or minutes > 59 or seconds > 59:
        return None
    if hours == _MAX_OFFSET_HOURS and (minutes > 0 or seconds > 0):
        return None
    total = hours * 3600 + minutes * 60 + seconds
    return -total if text[0] == "-" else total


def offset_id(seconds: int) -> str:
    """ZoneOffset.getId(): "Z" at zero, and seconds only when they are not zero."""
    if seconds == 0:
        return "Z"
    sign = "-" if seconds < 0 else "+"
    hours, remaining = divmod(abs(seconds), 3600)
    minutes, secs = divmod(remaining, 60)
    tail = f":{secs:02d}" if secs else ""
    return f"{sign}{hours:02d}:{minutes:02d}{tail}"


def normalize(value: str, region_names: frozenset[str]) -> str | None:
    """The ZoneId.getId() for a feed's timezone spelling, or None if invalid."""
    if value in region_names:
        return value
    for prefix in _PREFIXES:
        if not value.startswith(prefix):
            continue
        rest = value[len(prefix) :]
        if not rest:
            return prefix
        # ZoneId.of accepts "Z" only on its own, so "UTCZ" throws, while in "UTC+0"
        # a zero offset drops out of the ID entirely.
        if rest[0] not in "+-":
            return None
        seconds = offset_seconds(rest)
        if seconds is None:
            return None
        return prefix if seconds == 0 else prefix + offset_id(seconds)
    if value == "Z" or value[:1] in ("+", "-"):
        seconds = offset_seconds(value)
        return None if seconds is None else offset_id(seconds)
    return None
