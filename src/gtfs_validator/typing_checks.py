"""The stage 3 checks that are conditions rather than parse failures.

Six notices here fire on their own predicate instead of on a failed conversion:
missing_required_field, missing_recommended_field, invalid_character,
new_line_in_value, leading_or_trailing_whitespaces,
non_ascii_or_non_printable_char, mixed_case_recommended_field, and
number_out_of_range.

Upstream applies the string checks inside DefaultFieldValidator.validateField,
which RowParser calls only for columns the schema declares. That is why they
live here and not in the CSV parser: applying them to undeclared columns
inflates two counts on any feed carrying a stray column.
"""

from __future__ import annotations

import re
from decimal import Decimal

from gtfs_validator.javatext import trim, utf16_length
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.schema import Field, FieldType, Presence

REPLACEMENT_CHAR = "�"
PRINTABLE_ASCII_LOW = 32
PRINTABLE_ASCII_HIGH = 127

# Upstream splits on [^\p{L}]+. [\W\d_] is the Python spelling of "not a letter": a non-word
# character, a digit, or an underscore. Splitting rather than matching runs of letters is the whole
# point; see java_split_on_non_letters.
_NON_LETTER_RE = re.compile(r"[\W\d_]+", re.UNICODE)
_HAS_DIGIT_RE = re.compile(r"\d")


def java_split_on_non_letters(value: str) -> list[str]:
    """`value.split("[^\\p{L}]+")` with Java's semantics, which are not Python's.

    Two behaviours matter and neither is incidental:

    - A **leading** empty token is kept when the value starts with a delimiter, so `"33DP"` gives
      `["", "DP"]`. Digits are delimiters here, so this is every value beginning with a number. That
      empty token then counts as a token in `is_mixed_case`, which is what makes an all-caps
      `route_short_name` like `33DP` reportable. Reading tokens as runs of letters instead, which is
      what this code did until the real-feed corpus arrived, loses the token and the notice with it.
    - Trailing empty tokens are dropped, and a value with **no** letters at all therefore yields the
      empty list rather than `[""]`, because Java removes every trailing empty. `"123"` splits to
      nothing and reports nothing.

    Java's one special case is a subject with no delimiter at all, where split returns the whole
    string; Python's re.split does the same, so only the trailing-empty rule needs writing out.
    """
    if not _NON_LETTER_RE.search(value):
        return [value]
    parts = _NON_LETTER_RE.split(value)
    while parts and parts[-1] == "":
        parts.pop()
    return parts


# Upstream spells the expectation into the notice's fieldType, so this wording is
# part of the report rather than a description of it.
RANGE_LIMITS = {
    FieldType.LATITUDE: (-90.0, 90.0, "latitude within [-90, 90]"),
    FieldType.LONGITUDE: (-180.0, 180.0, "longitude within [-180, 180]"),
}
BOUNDS_PREDICATE = {
    "NON_NEGATIVE": (lambda value: value >= 0, "non-negative"),
    "POSITIVE": (lambda value: value > 0, "positive"),
    "NON_ZERO": (lambda value: value != 0, "non-zero"),
}


def cell_context(filename: str, row_number: int, field_name: str, value: object) -> dict:
    return {
        "filename": filename,
        "csvRowNumber": row_number,
        "fieldName": field_name,
        "fieldValue": value,
    }


def is_mixed_case(value: str) -> bool:
    """MixedCaseValidatorGenerator's algorithm, transliterated.

    One token: fine unless it is longer than a character, digit-free, and all
    lowercase. Several tokens: consider only those longer than a character and
    digit-free, then complain when at least two survive and none of them mixes an
    uppercase with a lowercase letter.

    "Longer than a character" is String.length(), so it counts UTF-16 units: a
    single astral lowercase letter is two units and does get considered.
    Measured: the jar reports mixed_case_recommended_field for a route_desc of
    one Deseret small letter, which len() sees as a single character and skips.
    """
    tokens = java_split_on_non_letters(value)
    if not tokens:
        return True
    if len(tokens) == 1:
        token = tokens[0]
        return not (utf16_length(token) > 1 and not _HAS_DIGIT_RE.search(token) and token.islower())
    # Upstream skips a token whose length is exactly 1, not one of length at most 1, and the
    # difference is the empty token a leading digit run produces: it counts, and counting it is what
    # takes a value like "33DP" to the two tokens the notice needs.
    considered = [t for t in tokens if utf16_length(t) != 1 and not _HAS_DIGIT_RE.search(t)]
    if len(considered) < 2:
        return True
    return any(
        any(c.isupper() for c in token) and any(c.islower() for c in token) for token in considered
    )


def check_presence(
    filename: str,
    field: Field,
    row_number: int,
    raw: str | None,
    notices: NoticeContainer,
) -> None:
    if raw:
        return
    context = {
        "filename": filename,
        "csvRowNumber": row_number,
        "fieldName": field.name,
    }
    if field.presence is Presence.REQUIRED:
        notices.add(Notice("missing_required_field", Severity.ERROR, context))
    elif field.presence is Presence.RECOMMENDED:
        notices.add(Notice("missing_recommended_field", Severity.WARNING, context))


def check_string(
    filename: str,
    field: Field,
    row_number: int,
    value: str,
    notices: NoticeContainer,
    mixed_case_pending: list[Notice] | None = None,
) -> str:
    """Run the string-level checks and return the value with whitespace trimmed.

    mixed_case_recommended_field is appended to ``mixed_case_pending`` when the
    caller supplies a list, rather than emitted directly. Upstream emits it from
    an entity validator that runs only for a clean row, so type_row holds these
    until it knows the row carried no ERROR. Without a list they go straight to
    ``notices``, which is what the unit tests use.
    """

    def report(code: str, severity: Severity, reported_value: str) -> None:
        notices.add(
            Notice(
                code,
                severity,
                cell_context(filename, row_number, field.name, reported_value),
            )
        )

    if REPLACEMENT_CHAR in value:
        # ERROR, not WARNING: the canonical manifest defines invalid_character as
        # ERROR, and a WARNING would also let a failed table slip past indexing.
        report("invalid_character", Severity.ERROR, value)
    if "\n" in value or "\r" in value:
        report("new_line_in_value", Severity.ERROR, value)

    trimmed = trim(value)
    if len(trimmed) < len(value):
        report("leading_or_trailing_whitespaces", Severity.WARNING, value)
        value = trimmed

    if field.type is FieldType.ID and not all(
        PRINTABLE_ASCII_LOW <= ord(c) < PRINTABLE_ASCII_HIGH for c in value
    ):
        # This one notice keys its column as "columnName", not "fieldName".
        notices.add(
            Notice(
                "non_ascii_or_non_printable_char",
                Severity.WARNING,
                {
                    "filename": filename,
                    "csvRowNumber": row_number,
                    "columnName": field.name,
                    "fieldValue": value,
                },
            )
        )

    if field.mixed_case and not is_mixed_case(value):
        notice = Notice(
            "mixed_case_recommended_field",
            Severity.WARNING,
            {
                "filename": filename,
                "fieldName": field.name,
                "fieldValue": value,
                "csvRowNumber": row_number,
            },
        )
        if mixed_case_pending is not None:
            mixed_case_pending.append(notice)
        else:
            notices.add(notice)
    return value


# The types whose notice carries the parsed value rather than a double: an int for INTEGER, and
# the BigDecimal itself for the two decimal-backed types. Everything else reports a Java double.
_EXACT_REPORT_TYPES = frozenset({FieldType.INTEGER, FieldType.DECIMAL, FieldType.CURRENCY_AMOUNT})


def check_number(
    filename: str,
    field: Field,
    row_number: int,
    value: float | Decimal,
    notices: NoticeContainer,
) -> None:
    """Check a parsed number's range, comparing exactly and reporting as the field's own type.

    The comparison and the report are not the same value for a Decimal. Upstream's checkBounds
    calls BigDecimal.compareTo(ZERO), so -1e-400 is negative and draws number_out_of_range,
    while the notice renders the double, which is "-0.0". Comparing the float instead would make
    the row look non-negative and keep it.

    But the *report* is the field's own type, and this converted every number to a double. Two
    corrections, one review each:

    - An **integer field reports an integer**. Measured on a stop_sequence of -1, where the jar
      sends `fieldValue: -1` and we sent `-1.0`.
    - A **DECIMAL or CURRENCY_AMOUNT reports its BigDecimal**, scale and all, because upstream
      passes the BigDecimal itself to the notice rather than a converted double. Measured: -1.20
      stays -1.20 where a float gives -1.2, an integral -2 stays -2, and -1e-400 stays -1E-400
      where a float gives -0.0, losing the value entirely.

    A float column keeps converting, and an integral one still renders -2.0, which is why the two
    cannot share a branch.
    """
    reported = value if field.type in _EXACT_REPORT_TYPES else float(value)

    def report(described_as: str) -> None:
        notices.add(
            Notice(
                "number_out_of_range",
                Severity.ERROR,
                {
                    "filename": filename,
                    "csvRowNumber": row_number,
                    "fieldName": field.name,
                    "fieldType": described_as,
                    "fieldValue": reported,
                },
            )
        )

    limits = RANGE_LIMITS.get(field.type)
    if limits and not (limits[0] <= value <= limits[1]):
        report(limits[2])
        return
    if field.bounds:
        predicate, label = BOUNDS_PREDICATE[field.bounds]
        if not predicate(value):
            # Upstream spells the number's kind into fieldType: an @NonNegative
            # @DecimalValue reads "non-negative decimal", not "float".
            if field.type is FieldType.INTEGER:
                kind = "integer"
            elif field.type in (FieldType.DECIMAL, FieldType.CURRENCY_AMOUNT):
                kind = "decimal"
            else:
                kind = "float"
            report(f"{label} {kind}")
