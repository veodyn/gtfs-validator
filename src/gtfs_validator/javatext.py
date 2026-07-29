"""Java string semantics that Python's look-alikes do not reproduce.

These are language-level differences rather than validator logic, which is why
they live beside the schema and notice modules rather than inside either the
field-type ports or the rule layer: both need them, and neither owns them.

Two differences bite repeatedly:

- A Java `String` is a sequence of UTF-16 code units, so `length()` counts an
  astral character twice where Python's `len` counts it once.
- `equalsIgnoreCase` compares code unit by code unit after single-unit case
  mapping, where Python's `casefold` applies full Unicode folding and can
  equate strings of different lengths.
"""

from __future__ import annotations

import math
import unicodedata
from decimal import Decimal


def utf16_units(value: str) -> list[int]:
    """The UTF-16 code units of a string, which is what Java iterates.

    An astral character becomes its surrogate pair, so comparisons that Java
    performs per unit can be reproduced per element of this list.
    """
    units: list[int] = []
    for char in value:
        code_point = ord(char)
        if code_point > 0xFFFF:
            offset = code_point - 0x10000
            units.append(0xD800 + (offset >> 10))
            units.append(0xDC00 + (offset & 0x3FF))
        else:
            units.append(code_point)
    return units


def utf16_length(value: str) -> int:
    """Java CharSequence.length(), which counts UTF-16 code units.

    Measured on route_short_name_too_long, whose cap is 12: a short name of
    seven astral characters is 7 to Python and 14 to Java, and the jar reports
    it while counting code points does not.

    **Two fast paths, because this is on the hot path for every feed.** Profiling a real 997,334-row
    feed showed this called 6,160,072 times, with the per-character generator it used to be running
    172,105,692 times, about a seventh of the whole run. An ASCII string, which is nearly all of
    them, now answers from `len`, and anything else is measured with one encode in C rather than a
    Python loop per character. The arithmetic is the same: UTF-16 length is the code point count
    plus one extra unit for each character above the BMP, which is exactly what the encoding's byte
    count over two gives.
    """
    if value.isascii():
        return len(value)
    return len(value.encode("utf-16-le", "surrogatepass")) // 2


# Character.toLowerCase uses UnicodeData's *simple* mapping, one code point to
# one code point. Python's str.lower applies the full mapping from
# SpecialCasing.txt, and exactly one entry there is both unconditional and longer
# than a single character: the dotted capital I, whose full lowercase is "i" plus
# a combining dot above while its simple lowercase is plain "i". Every other
# multi-character lowercase mapping is conditional (final sigma, or locale
# specific) and Python does not apply those, so this table needs no other rows.
_SIMPLE_LOWER_EXCEPTIONS = {0x0130: 0x0069}


def _simple_upper(code_point: int) -> int:
    """Character.toUpperCase, which maps one code point to one code point.

    Where the full uppercase mapping is longer than a single character, Java's
    simple mapping leaves the character alone: the sharp s stays a sharp s
    rather than becoming "SS". str.upper applies the full mapping, so the length
    guard is what selects the simple behaviour.
    """
    upper = chr(code_point).upper()
    return ord(upper) if len(upper) == 1 else code_point


def _simple_lower(code_point: int) -> int:
    """Character.toLowerCase, likewise simple rather than full."""
    if code_point in _SIMPLE_LOWER_EXCEPTIONS:
        return _SIMPLE_LOWER_EXCEPTIONS[code_point]
    lower = chr(code_point).lower()
    return ord(lower) if len(lower) == 1 else code_point


def equals_ignore_case(left: str, right: str) -> bool:
    """String.equalsIgnoreCase, which is neither casefold nor lower() equality.

    Three details, each measured against the jar rather than inferred:

    - The length test is in UTF-16 code units. casefold instead applies full
      folding and equates "Strasse" with the sharp-s spelling, whose unit
      lengths differ; the jar reports the plain spelling only.
    - The comparison is per code point, not per code unit. A Deseret capital
      and its small form are a surrogate pair each, and their low surrogates
      differ, yet the jar treats them as equal.
    - The third test lowercases the *uppercased* pair rather than the originals.
      That is what makes the dotted capital I equal to "i": their uppercase
      forms differ, and only after uppercasing does lowercasing bring them
      together.
    """
    if utf16_length(left) != utf16_length(right):
        return False
    left_points = [ord(char) for char in left]
    right_points = [ord(char) for char in right]
    # Equal unit lengths with different code point counts means the two differ in
    # surrogate structure, so no pairing exists.
    if len(left_points) != len(right_points):
        return False
    for first, second in zip(left_points, right_points, strict=True):
        if first == second:
            continue
        upper_first, upper_second = _simple_upper(first), _simple_upper(second)
        if upper_first == upper_second:
            continue
        if _simple_lower(upper_first) == _simple_lower(upper_second):
            continue
        return False
    return True


# Java's trim boundary. String.trim removes every code unit at or below the
# space, which is not the same set as Python's str.strip: a no-break space is
# stripped by Python and kept by Java.
TRIM_CEILING = "\u0020"

# Character.isWhitespace excludes the non-breaking space separators, which
# str.isspace includes. This is a third rule again, distinct from trim's: a
# vertical tab is whitespace to both, a no-break space to neither Java test, and
# an em space to isWhitespace but not to trim.
NON_BREAKING_SPACES = frozenset("\u00a0\u2007\u202f")


def trim(value: str) -> str:
    """String.trim(), which removes code units at or below U+0020.

    DefaultFieldValidator calls this before comparing lengths, so it decides
    both leading_or_trailing_whitespaces and the value every later check sees.
    str.strip removes Unicode whitespace instead, which reported a whitespace
    notice the jar does not and then handed an empty string to the field
    parsers: measured on a feed_contact_email of one no-break space, where the
    jar reports invalid_email carrying that character and we reported it
    carrying "".
    """
    start, end = 0, len(value)
    while start < end and value[start] <= TRIM_CEILING:
        start += 1
    while end > start and value[end - 1] <= TRIM_CEILING:
        end -= 1
    return value[start:end]


def double_string(value: float) -> str:
    """`Double.toString`, which is how a Java double reaches a report as a string.

    Java keeps a digit either side of the point, so 7 renders "7.0" where Python's `str` gives
    "7", and it uses scientific notation outside [1e-3, 1e7), spelled with one digit before the
    point and an `E` with no plus sign: 1e-4 is "1.0E-4" and 1e7 is "1.0E7".

    The notation has to be *constructed* rather than taken from `repr`, which was the defect a
    review found: `repr(1e-4)` is "0.0001" and `repr(1e7)` is "10000000.0", neither carrying an
    exponent, so a first version that only reformatted when it saw an "e" left both unchanged and
    disagreed with the jar on ids a feed can hold.

    **Known residue, measured:** JDK 17 predates the shortest-repr algorithm, so for a few values
    its digits are not Python's. The minimum subnormal is the case a review found: the jar writes
    "4.9E-324" and this writes "5.0E-324". Of the nine numeric feature ids in that probe, that one
    differs and the other eight agree. Closing it means porting `FloatingDecimal`. Recorded in
    a comment naming the measured cases rather than a docstring saying it does not matter, which is
    what this docstring said before the review disproved it.
    """
    if value != value:
        return "NaN"
    if value == float("inf"):
        return "Infinity"
    if value == float("-inf"):
        return "-Infinity"
    number = float(value)
    magnitude = abs(number)
    if magnitude == 0:
        return "-0.0" if math.copysign(1.0, number) < 0 else "0.0"
    if 1e-3 <= magnitude < 1e7:
        text = repr(number)
        return text if "." in text else text + ".0"
    sign, digits, exponent = Decimal(repr(number)).as_tuple()
    # Java's scientific form is one digit, a point, the remaining digits, then the exponent of
    # the leading digit. Trailing zeros are dropped, and a lone digit still needs its ".0".
    significant = "".join(str(digit) for digit in digits).rstrip("0") or "0"
    mantissa = significant if len(significant) == 1 else f"{significant[0]}.{significant[1:]}"
    if "." not in mantissa:
        mantissa += ".0"
    power = len(digits) + int(exponent) - 1
    return f"{'-' if sign else ''}{mantissa}E{power}"


def ascii_to_lower(value: str) -> str:
    """`com.google.common.base.Ascii.toLowerCase`, which touches A-Z and nothing else.

    Python's `str.lower` is Unicode-aware, so it also maps `Ä` to `ä` and expands `İ` into two
    code points. Guava's does neither, and the difference is observable: measured on a feed
    whose agency_url is `https://Ä.example.com/` and whose stop_url is `https://ä.example.com/`,
    where the jar reports no same_stop_and_agency_url and `str.lower` would have matched them.
    """
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in value)


def compare_to(left: str, right: str) -> int:
    """String.compareTo, which compares UTF-16 code units and then lengths.

    Python compares code points, which agrees for BMP-only strings and disagrees the
    moment an astral character meets one above U+DFFF: a surrogate leads with 0xD800
    while Python sees U+1F600 as greater than U+FFFD. HashMap's treeified bins order
    equal-hash keys with this method, so the disagreement decides which notices survive
    the 1,000-sample cap.
    """
    ours, theirs = utf16_units(left), utf16_units(right)
    for one, other in zip(ours, theirs, strict=False):
        if one != other:
            return one - other
    return len(ours) - len(theirs)


def is_blank(value: str) -> bool:
    """String.isBlank(), which tests Character.isWhitespace over the string."""
    return all(char.isspace() and char not in NON_BREAKING_SPACES for char in value)


# Integer.parseInt's range. Beyond it the method throws, like any other bad input.
_INT_MIN = -(2**31)
_INT_MAX = 2**31 - 1


def parse_int(text: str) -> int | None:
    """`Integer.parseInt`, or None where it would throw NumberFormatException.

    Not the same as the typing stage's integer parser, and the difference is measurable:
    `Character.digit` accepts any Unicode decimal digit, so `Integer.parseInt("\u0661")` is 1 and
    a translations row spelling a stop_sequence with an Arabic-Indic digit **matches** the stored
    1. Our field parser is deliberately ASCII-only because upstream's field parsing is; this is
    the other path, used by the generated byTranslationKey conversions.

    A leading + or - is allowed and nothing else is: no spaces, no underscores, no grouping.
    """
    if not text:
        return None
    body = text[1:] if text[0] in "+-" else text
    if not body:
        return None
    value = 0
    for character in body:
        if unicodedata.category(character) != "Nd":
            return None
        value = value * 10 + unicodedata.decimal(character)
    if text[0] == "-":
        value = -value
    return value if _INT_MIN <= value <= _INT_MAX else None
