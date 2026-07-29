"""Per-table compiled cell processors: the typing stage's hot loop, bound once.

`type_row` used to decide per cell what kind of field it was looking at: enum
membership tests against frozensets of FieldType, dict lookups for the parser and the
notice code, and a chain of string checks that each walked the value again. Profiled
on a real 5.2-million-row feed that was 31 million `_parse_value` calls, 271 million
`dict.get`s and 116 million enum hashes, about a third of the whole run. Everything
in that chain is a function of the *field*, not of the value, so it is decided here,
once per table, and the per-cell closure does only the work the field can need.

The semantics are the typing stage's, unchanged; the notice dicts are written with
the same keys in the same order, and the slow string path *is*
`typing_checks.check_string`, called not reimplemented. The fast path is the one
liberty: a value made entirely of printable ASCII with no space cannot draw
invalid_character, new_line_in_value, leading_or_trailing_whitespaces or the
non-ASCII ID notice, and cannot be changed by `trim`, so one C-level regex search
replaces those four walks and only the mixed-case check remains.
"""

from __future__ import annotations

import re
from decimal import Decimal

from gtfs_validator.fieldtypes import scalars
from gtfs_validator.fieldtypes.phones import is_possible_phone_number
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.schema import Field, FieldType, Presence, TableSchema, unrecognized_value
from gtfs_validator.typing_checks import (
    BOUNDS_PREDICATE,
    RANGE_LIMITS,
    check_string,
    is_mixed_case,
)
from gtfs_validator.typing_maps import (
    EXACT_REPORT_TYPES,
    PARSE_NOTICE,
    PARSERS,
    PASSTHROUGH_TYPES,
    VALIDATED_TYPES,
    VALIDATORS,
)

# A cell the string checks cannot touch: printable ASCII, no space, so no trim, no
# newline, no replacement character and nothing the ID printability test rejects.
_NEEDS_SLOW_STRING_PATH = re.compile(r"[^\x21-\x7e]").search

# The sentinel `type_row` passes for a column the header never declared, which is a
# different case from a declared column whose cell is empty.
ABSENT = object()

# Compiled processors per schema object, keyed by id with the schema pinned so the id
# cannot be reused. Tests build ad-hoc schemas by the hundred; fourteen real tables
# and those together stay small.
_COMPILED: dict[tuple[int, str], tuple[TableSchema, list]] = {}


def compiled_cells(schema: TableSchema, country_code: str) -> list:
    key = (id(schema), country_code)
    cached = _COMPILED.get(key)
    if cached is None:
        cells = [
            (field.name, _cell(schema.filename, field, country_code)) for field in schema.fields
        ]
        cached = (schema, cells)
        _COMPILED[key] = cached
    return cached[1]


def _cell(filename: str, field: Field, country_code: str):
    """One field's whole per-cell behaviour, every decision about the field prebound."""
    name = field.name
    required = field.presence is Presence.REQUIRED
    recommended = field.presence is Presence.RECOMMENDED
    check_mixed = field.mixed_case
    convert = _converter(filename, field, country_code)
    needs_slow = _NEEDS_SLOW_STRING_PATH

    def cell(raw, row_number, notices, pending):
        if raw is ABSENT:
            # The column is absent from the header entirely, and upstream treats the
            # two presence levels differently here: an absent REQUIRED column draws
            # missing_required_column once in stage 2 and nothing per row, while an
            # absent RECOMMENDED column draws missing_recommended_field on every row.
            if recommended:
                notices.add(
                    Notice(
                        "missing_recommended_field",
                        Severity.WARNING,
                        {"filename": filename, "csvRowNumber": row_number, "fieldName": name},
                    )
                )
            return None
        if not raw:
            if required:
                notices.add(
                    Notice(
                        "missing_required_field",
                        Severity.ERROR,
                        {"filename": filename, "csvRowNumber": row_number, "fieldName": name},
                    )
                )
            elif recommended:
                notices.add(
                    Notice(
                        "missing_recommended_field",
                        Severity.WARNING,
                        {"filename": filename, "csvRowNumber": row_number, "fieldName": name},
                    )
                )
            return None
        if needs_slow(raw) is None:
            value = raw
            if check_mixed and not is_mixed_case(value):
                pending.append(
                    Notice(
                        "mixed_case_recommended_field",
                        Severity.WARNING,
                        {
                            "filename": filename,
                            "fieldName": name,
                            "fieldValue": value,
                            "csvRowNumber": row_number,
                        },
                    )
                )
        else:
            value = check_string(filename, field, row_number, raw, notices, pending)
        if convert is None:
            return value
        return convert(value, row_number, notices)

    return cell


def _converter(filename: str, field: Field, country_code: str):
    """The type-specific half of the cell, or None for a passthrough type."""
    if field.type in PASSTHROUGH_TYPES:
        return None
    if field.type in VALIDATED_TYPES:
        return _validated(filename, field, country_code)
    if field.type is FieldType.ENUM:
        return _enum(filename, field)
    return _parsed(filename, field)


def _context(filename: str, name: str):
    def context(row_number: int, value) -> dict:
        return {
            "filename": filename,
            "csvRowNumber": row_number,
            "fieldName": name,
            "fieldValue": value,
        }

    return context


def _validated(filename: str, field: Field, country_code: str):
    if field.type is FieldType.PHONE_NUMBER:
        ok, code = (
            (lambda value: is_possible_phone_number(value, country_code)),
            ("invalid_phone_number"),
        )
    else:
        ok, code = VALIDATORS[field.type]
    context = _context(filename, field.name)

    def convert(value, row_number, notices):
        if not ok(value):
            notices.add(Notice(code, Severity.ERROR, context(row_number, value)))
        return value

    return convert


def _enum(filename: str, field: Field):
    parse_integer = scalars.parse_integer
    parse_error = scalars.ParseError
    enum_values = field.enum_values
    unrecognized = unrecognized_value(field)
    context = _context(filename, field.name)
    name = field.name

    def convert(value, row_number, notices):
        parsed = parse_integer(value)
        if isinstance(parsed, parse_error):
            notices.add(Notice("invalid_integer", Severity.ERROR, context(row_number, value)))
            return None
        if enum_values is not None and parsed not in enum_values:
            notices.add(
                Notice(
                    "unexpected_enum_value",
                    Severity.WARNING,
                    {
                        "filename": filename,
                        "csvRowNumber": row_number,
                        "fieldName": name,
                        # The raw integer, before the value is folded to UNRECOGNIZED.
                        "fieldValue": parsed,
                    },
                )
            )
            # Upstream stores the *enum*, so an unrecognised value becomes
            # UNRECOGNIZED, whose number EnumGenerator defines as min(values) - 1.
            # Every rule that reads an enum then sees that rather than the raw
            # integer: a calendar monday of 2 folds to -1, and
            # weeklyPatternFromMTWTFSS masks the value with 1, so -1 sets the Monday
            # bit where 2 clears it. Measured: the jar expands such a service and
            # reports expired_calendar for it.
            return unrecognized
        return parsed

    return convert


def _parsed(filename: str, field: Field):
    parser = PARSERS[field.type]
    parse_error = scalars.ParseError
    failure_code = PARSE_NOTICE[field.type]
    context = _context(filename, field.name)
    number_check = _number_check(filename, field)

    def convert(value, row_number, notices):
        parsed = parser(value)
        if isinstance(parsed, parse_error):
            notices.add(Notice(failure_code, Severity.ERROR, context(row_number, value)))
            return None
        if number_check is not None and isinstance(parsed, (int, float, Decimal)):
            # A Decimal (DECIMAL, CURRENCY_AMOUNT) carries the same bounds as a float
            # field, but it is compared unconverted: checkBounds compares the
            # BigDecimal, and rounding to a double first loses the sign of a tiny
            # negative like -1e-400.
            number_check(parsed, row_number, notices)
        return parsed

    return convert


def _number_check(filename: str, field: Field):
    """The range check, or None for the many fields that have nothing to check.

    Prebinding the labels is what upstream's checkBounds spells into the notice's
    fieldType: an @NonNegative @DecimalValue reads "non-negative decimal". An integer
    field reports an integer and a decimal-backed field its BigDecimal, scale and
    all; everything else reports a Java double.
    """
    limits = RANGE_LIMITS.get(field.type)
    bounds = BOUNDS_PREDICATE[field.bounds] if field.bounds else None
    if limits is None and bounds is None:
        return None
    exact = field.type in EXACT_REPORT_TYPES
    if field.type is FieldType.INTEGER:
        kind = "integer"
    elif field.type in (FieldType.DECIMAL, FieldType.CURRENCY_AMOUNT):
        kind = "decimal"
    else:
        kind = "float"
    bound_label = f"{bounds[1]} {kind}" if bounds else ""
    name = field.name

    def check(value, row_number, notices):
        def report(described_as: str) -> None:
            notices.add(
                Notice(
                    "number_out_of_range",
                    Severity.ERROR,
                    {
                        "filename": filename,
                        "csvRowNumber": row_number,
                        "fieldName": name,
                        "fieldType": described_as,
                        "fieldValue": value if exact else float(value),
                    },
                )
            )

        if limits is not None and not (limits[0] <= value <= limits[1]):
            report(limits[2])
            return
        if bounds is not None and not bounds[0](value):
            report(bound_label)

    return check
