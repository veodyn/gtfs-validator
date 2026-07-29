"""The string-level steps parse() runs before any metadata is consulted.

Everything here works on the number as text: trimming it to a plausible
candidate, checking viability, folding letters and Unicode digits to ASCII, and
stripping the extension, the RFC 3966 parameters and a dialling prefix. The
decisions that need a region's metadata live in phones.py.

The split follows parseHelper's own shape, and keeps each file readable: the
sequencing is hard enough to check without the length tables interleaved.
"""

from __future__ import annotations

import re
import unicodedata

from gtfs_validator.fieldtypes.phone_tables import (
    FROM_DEFAULT_COUNTRY,
    FROM_NUMBER_WITH_IDD,
    FROM_NUMBER_WITH_PLUS_SIGN,
    MAX_LENGTH_COUNTRY_CODE,
    MIN_LENGTH_FOR_NSN,
    PLUS_CHARS,
    alpha_mappings,
    constant,
    java_regex,
    pattern,
    tables,
)

_VALID_START_CHAR_RE = re.compile(rf"[{re.escape(PLUS_CHARS)}\d]")
_PLUS_CHARS_RE = re.compile(rf"[{re.escape(PLUS_CHARS)}]+")
_CAPTURING_DIGIT_RE = re.compile(r"(\d)")


def _is_unwanted_end_char(char: str) -> bool:
    """UNWANTED_END_CHAR_PATTERN: neither a number nor a letter, and not "#".

    Java spells this as a character-class intersection, which Python's re has no
    syntax for, so the membership test is written out instead.
    """
    return char != "#" and unicodedata.category(char)[0] not in ("N", "L")


def extract_possible_number(number: str) -> str:
    match = _VALID_START_CHAR_RE.search(number)
    if not match:
        return ""
    number = number[match.start() :]
    while number and _is_unwanted_end_char(number[-1]):
        number = number[:-1]
    second = pattern("SECOND_NUMBER_START_PATTERN").search(number)
    if second:
        number = number[: second.start()]
    return number


def is_viable_phone_number(value: str) -> bool:
    """PhoneNumberUtil.isViablePhoneNumber, the precondition inside parse()."""
    if len(value) < MIN_LENGTH_FOR_NSN:
        return False
    return bool(pattern("VALID_PHONE_NUMBER_PATTERN").fullmatch(value))


def normalize_digits_only(number: str) -> str:
    r"""normalizeDigitsOnly, which keeps a decimal digit only if it is one char.

    Java iterates UTF-16 code units and calls Character.digit(char, 10), so a
    supplementary-plane digit arrives as two surrogate halves and neither is a
    digit: the whole character is dropped. Iterating Python code points instead
    folds it, which turns an Osmanya rendering of a US number into a valid one.
    The viability pattern is no help here, because Java matches \p{Nd} by code
    point and so does accept those digits a step earlier.
    """
    return "".join(
        str(unicodedata.decimal(c))
        for c in number
        if ord(c) <= 0xFFFF and unicodedata.decimal(c, -1) != -1
    )


def normalize(number: str) -> str:
    if pattern("VALID_ALPHA_PHONE_PATTERN").fullmatch(number):
        mappings = alpha_mappings()
        return "".join(mappings.get(c.upper(), "") for c in number)
    return normalize_digits_only(number)


def strip_extension(number: str) -> str:
    match = pattern("EXTN_PATTERN").search(number)
    if match and is_viable_phone_number(number[: match.start()]):
        for group in match.groups():
            if group is not None:
                return number[: match.start()]
    return number


def _parse_prefix_as_idd(idd: str, number: str) -> str | None:
    """Strip an international dialling prefix, unless a zero follows it.

    A country calling code cannot begin with zero, so a match followed by one is
    not a dialling prefix at all.
    """
    match = re.compile(java_regex(idd)).match(number)
    if not match:
        return None
    rest = number[match.end() :]
    digit = _CAPTURING_DIGIT_RE.search(rest)
    if digit and normalize_digits_only(digit.group(1)) == "0":
        return None
    return rest


def strip_international_prefix(number: str, idd: str) -> tuple[str, str]:
    if not number:
        return FROM_DEFAULT_COUNTRY, number
    plus = _PLUS_CHARS_RE.match(number)
    if plus:
        return FROM_NUMBER_WITH_PLUS_SIGN, normalize(number[plus.end() :])
    normalized = normalize(number)
    if idd:
        stripped = _parse_prefix_as_idd(idd, normalized)
        if stripped is not None:
            return FROM_NUMBER_WITH_IDD, stripped
    return FROM_DEFAULT_COUNTRY, normalized


def extract_country_code(full: str) -> tuple[int, str]:
    """The shortest prefix that is a known calling code wins, not the longest.

    libphonenumber walks i = 1..3 and returns on the first hit, so "+1..." is
    always calling code 1 even where a three-digit code shares the prefix.
    """
    if not full or full[0] == "0":
        return 0, ""
    codes = tables()["code_regions"]
    for i in range(1, min(MAX_LENGTH_COUNTRY_CODE, len(full)) + 1):
        candidate = full[:i]
        if candidate in codes:
            return int(candidate), full[i:]
    return 0, ""


def build_national_number_for_parsing(value: str) -> str:
    """buildNationalNumberForParsing, which runs before the viability check.

    An RFC 3966 "tel:" URI carries its parameters after the number, and parse()
    strips them here rather than letting extractPossibleNumber trip over them.
    Only a phone-context that is itself a number prefix is kept; a domain one is
    dropped. Measured against the jar: this build has no phone-context validity
    check at all, so "phone-context=!!!" is simply ignored rather than fatal.

    The isdn-subaddress is cut from whichever branch produced the number, which
    is why ";isub=" works without a "tel:" prefix or a phone-context.
    """
    marker = constant("RFC3966_PHONE_CONTEXT")
    index = value.find(marker)
    if index == -1:
        national = extract_possible_number(value)
    else:
        start = index + len(marker)
        end = value.find(";", start)
        context = "" if start >= len(value) else (value[start:end] if end != -1 else value[start:])
        # A context holding a country calling code becomes part of the number; a
        # domain is ignored.
        national = context if context[:1] == "+" else ""
        prefix = constant("RFC3966_PREFIX")
        prefix_index = value.find(prefix)
        number_start = prefix_index + len(prefix) if prefix_index >= 0 else 0
        national += value[number_start:index]

    isdn = national.find(constant("RFC3966_ISDN_SUBADDRESS"))
    if isdn > 0:
        national = national[:isdn]
    return national


def match_java_regex(raw: str, value: str) -> bool:
    """Full-match a dumped Java regex, used for the per-region metadata patterns.

    These are not in the pattern table, so they carry no flags of their own;
    libphonenumber matches them with none set.
    """
    return bool(re.compile(java_regex(raw)).fullmatch(value))


def starts_with_plus(value: str) -> bool:
    """PLUS_CHARS_PATTERN.lookingAt, the test checkRegionForParsing applies."""
    return bool(_PLUS_CHARS_RE.match(value))


def plus_prefix_length(value: str) -> int:
    """How many leading plus characters there are, which may be more than one."""
    match = _PLUS_CHARS_RE.match(value)
    return match.end() if match else 0
