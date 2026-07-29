"""What the four `TranslationFieldAndReferenceValidator` codes share.

This is the first rule that reads a table chosen at *runtime*: each translations row names
its parent in `table_name`, and the parent's key columns decide what else the row must carry.
Three things follow, all measured on the jar.

**The whole feed is the dependency.** The validator is injected with the feed container, not
with individual tables, so *any* table failing to load skips it. Measured: a feed whose
stops.txt has a short row reports nothing about a translations row naming `feed_info`, a table
that loaded perfectly.

**One bad row silences the rest.** The first pass reports `missing_required_field` for every
row lacking `field_name`, `language` or `table_name`, and if any row did, the validator
returns before looking at references. So a feed can draw the missing-field notices and none of
the other three codes.

**Key column count decides what is expected.** Not the parent's contents, its *schema*:

| Parent key columns | record_id | record_sub_id | Example |
|---|---|---|---|
| 0 | forbidden | forbidden | feed_info.txt |
| 1 | required | forbidden | stops.txt |
| 2 or more | required | required | stop_times.txt |

A field that is present when forbidden is `translation_unexpected_value`; absent when required
is `missing_required_field`. Either one stops that row before the reference lookup.
"""

from __future__ import annotations

import datetime
import re

from gtfs_validator import javatext
from gtfs_validator.rules._shared import locales
from gtfs_validator.schema import FieldType, load_schemas

FILENAME = "translations.txt"
TABLE_NAME = "table_name"
FIELD_NAME = "field_name"
LANGUAGE = "language"
RECORD_ID = "record_id"
RECORD_SUB_ID = "record_sub_id"
FIELD_VALUE = "field_value"

STANDARD_REQUIRED = (FIELD_NAME, LANGUAGE, TABLE_NAME)
_CACHE_KEY = "translations.rows"


def rows_of(feed) -> list[dict]:
    """Every translations row, cached, or nothing when the validator cannot run.

    Empty covers all three ways upstream declines: a failed table anywhere in the feed, a
    translations.txt that does not declare `table_name`, and a translations.txt that failed
    to load. Callers therefore need no gate of their own beyond `first_pass_failed`.
    """
    cached = feed.cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    rows: list[dict] = []
    if feed.has_column(FILENAME, TABLE_NAME) and not feed.whole_feed_failed():
        rows = list(feed.rows(FILENAME))
    feed.cache[_CACHE_KEY] = rows
    return rows


def missing_standard_fields(rows: list[dict]) -> list[tuple[int, str]]:
    """`validateStandardRequiredFields`: (row number, field) for each absent required field.

    Reported in field order per row, which is the order upstream tests them in.
    """
    return [
        (row["_row_number"], field)
        for row in rows
        for field in STANDARD_REQUIRED
        if row.get(field) is None
    ]


def first_pass_failed(rows: list[dict]) -> bool:
    """Whether the first pass found anything, which stops the other three codes."""
    return bool(missing_standard_fields(rows))


def parent_filename(row: dict) -> str:
    return f"{row.get(TABLE_NAME) or ''}.txt"


RECORD_ID_TYPE = "RECORD_ID"
RECORD_SUB_ID_TYPE = "RECORD_SUB_ID"
_UNCONVERTIBLE = object()


def translation_types(filename: str) -> tuple[str, ...]:
    """Which translations id each of the parent's key columns matches, from the schema."""
    schema = load_schemas().get(filename)
    return () if schema is None else schema.primary_key_translation_types


def key_columns(filename: str) -> tuple[str, ...] | None:
    """The parent's key columns, or None when no such table exists in GTFS at all.

    None and "a table this feed does not carry" both end as
    `translation_unknown_table_name`, but they are different questions and only the caller
    knows whether the file is present.
    """
    schemas = load_schemas()
    schema = schemas.get(filename)
    return None if schema is None else schema.primary_key


def expected_ids(keys: tuple[str, ...]) -> tuple[bool, bool]:
    """Whether record_id and record_sub_id are expected, from the key column count."""
    return len(keys) >= 1, len(keys) >= 2


def presence_checks(keys: tuple[str, ...]) -> tuple[tuple[str, bool], ...]:
    """The two presence checks in upstream's order, for a caller that stops at the first.

    `isMissingOrUnexpectedField(record_id) || isMissingOrUnexpectedField(record_sub_id)` is
    short-circuiting, so a record_id with the wrong presence means record_sub_id is never
    examined. Measured: checking both independently reported three notices where the jar
    reports two.
    """
    wants_id, wants_sub_id = expected_ids(keys)
    return ((RECORD_ID, wants_id), (RECORD_SUB_ID, wants_sub_id))


def resolvable_rows(feed, rows: list[dict]) -> list[dict]:
    """The rows that get as far as a reference lookup: parent present, no field_value."""
    resolvable = []
    for row in rows:
        if row.get(FIELD_VALUE) is not None:
            continue
        parent = parent_filename(row)
        if key_columns(parent) is None or feed.is_missing(parent):
            continue
        resolvable.append(row)
    return resolvable


def existing_keys(feed, rows: list[dict]) -> set[tuple[str, str, str]]:
    """Which (parent, record_id, record_sub_id) triples `byTranslationKey` would resolve.

    Upstream *generates* this method per table, and it has four shapes. They are not
    interchangeable, and treating them all as string equality against the primary key produced
    false violations on ordinary feeds:

    | Table shape | Lookup |
    |---|---|
    | one key column | that column against `record_id`, as a string |
    | two or more, at least one annotated | a composite key over **every** key column |
    | `singleRow` | the first row, if the table has one |
    | anything else | always empty, so every such translation violates |

    The composite case is the subtle one. Each key column takes `record_id` or `record_sub_id`
    if it is annotated for one, **converted to the column's own type**, and the column's default
    if it is not annotated or the id is empty. So `transfers`, whose first two key columns are
    annotated and whose other four are UNSUPPORTED, only matches a row whose other four are
    at their defaults, and `frequencies.start_time` matches "08:00:00" against the stored
    seconds because the value is parsed before comparison. A conversion that fails is a
    NumberFormatException upstream and simply does not match.

    One pass per distinct parent table, matching only the keys the translations rows ask about:
    a lookup per row would re-walk stop_times.txt once per translation, and collecting every
    key in the parent would hold the largest table in the feed.
    """
    wanted: dict[str, set[tuple[str, str]]] = {}
    for row in rows:
        parent = parent_filename(row)
        wanted.setdefault(parent, set()).add(
            (row.get(RECORD_ID) or "", row.get(RECORD_SUB_ID) or "")
        )

    found: set[tuple[str, str, str]] = set()
    for parent, keys in wanted.items():
        found |= _resolve_in(feed, parent, keys)
    return found


def _resolve_in(feed, parent: str, keys: set[tuple[str, str]]) -> set[tuple[str, str, str]]:
    schema = load_schemas().get(parent)
    if schema is None:
        return set()
    columns = schema.primary_key
    types = translation_types(parent)

    if len(columns) == 1:
        wanted_ids = {record_id for record_id, _ in keys}
        matched = {
            row.get(columns[0]) for row in feed.rows(parent) if row.get(columns[0]) in wanted_ids
        }
        return {(parent, record_id, sub_id) for record_id, sub_id in keys if record_id in matched}

    if len(columns) >= 2 and any(kind in (RECORD_ID_TYPE, RECORD_SUB_ID_TYPE) for kind in types):
        return _resolve_composite(feed, parent, schema, columns, types, keys)

    if schema.single_row:
        # `entities.isEmpty() ? empty : Optional.of(entities.get(0))`: any row will do, and the
        # ids are not consulted at all. A present but header-only table therefore violates.
        has_row = any(True for _ in feed.rows(parent))
        return {(parent, record_id, sub_id) for record_id, sub_id in keys} if has_row else set()

    # No key columns, or a multi-column key with nothing annotated, as stop_areas has: the
    # generated method returns Optional.empty() unconditionally, so every such translation is
    # a violation.
    return set()


def _resolve_composite(feed, parent, schema, columns, types, keys) -> set[tuple[str, str, str]]:
    expected: dict[tuple[str, str], tuple | None] = {}
    for record_id, sub_id in keys:
        expected[(record_id, sub_id)] = _composite_key(schema, columns, types, record_id, sub_id)

    found: set[tuple[str, str, str]] = set()
    for row in feed.rows(parent):
        actual = tuple(row.get(column) for column in columns)
        for (record_id, sub_id), wanted in expected.items():
            if wanted is not None and actual == wanted:
                found.add((parent, record_id, sub_id))
    return found


def _composite_key(schema, columns, types, record_id: str, sub_id: str) -> tuple | None:
    """The key upstream builds, or None when a conversion would have thrown."""
    values = []
    for column, kind in zip(columns, types, strict=True):
        field = schema.field(column)
        source = {RECORD_ID_TYPE: record_id, RECORD_SUB_ID_TYPE: sub_id}.get(kind)
        if not source:
            # Unannotated, or the id is empty: the entity default, which our store spells as an
            # absent value.
            values.append(_default_for(field))
            continue
        converted = _convert(field, source)
        if converted is _UNCONVERTIBLE:
            return None
        values.append(converted)
    return tuple(values)


def _default_for(field) -> object:
    """The entity default, as the store would hold it.

    Our store holds an absent value as NULL, and upstream's generated entity returns the type
    default, so a key column at its default reads as None here. An integer column is the
    exception worth naming: 0 is a real stored value that also happens to be the default, and
    the absent-integer key defect in state-of-play is the same confusion.
    """
    if field is not None and field.type is FieldType.INTEGER:
        return None
    return None


class TranslationConversionError(Exception):
    """A conversion that throws IllegalArgumentException, which upstream does not catch.

    The generated method catches `NumberFormatException` only, so a bad *integer* key becomes a
    lookup miss while a bad date or time propagates out of `byTranslationKey` and aborts
    `TranslationFieldAndReferenceValidator` entirely. Measured on both: a translations row
    naming calendar_dates with record_sub_id `notadate` produces no translation notices at all
    and one `runtime_exception_in_validator_error`, while `notanint` against stop_sequence
    produces an ordinary foreign key violation.

    Letting this escape the rule gives the runner the same outcome: the rule's notices are
    discarded and a runtime exception is recorded.
    """


# GtfsTime.fromString's pattern, spelled with an explicit [0-9] rather than \d. Java's \d is
# ASCII-only without UNICODE_CHARACTER_CLASS while Python's is not, so \d here would have matched
# an Arabic-Indic digit that the jar rejects. That is the whole point of this pattern: the same
# Arabic-Indic digit is accepted by Integer.parseInt and refused by this regex, so an integer key
# and a time key behave differently on it. Measured on both.
_TIME_PATTERN = re.compile(r"\A([0-9]{1,3}):([0-9]{2}):([0-9]{2})\Z")
_DATE_LENGTH = 8
_MINUTES_PER_HOUR = 60
_SECONDS_PER_MINUTE = 60


def _java_date(value: str) -> int:
    """`GtfsDate.fromString`, as the store's YYYYMMDD integer.

    Length is checked first, then each part goes through `Integer.parseInt` on a *substring*,
    which is why `2026+101` is a valid date: the month substring is `+1`. Measured.
    """
    if len(value) != _DATE_LENGTH:
        raise TranslationConversionError(f"Date must have YYYYMMDD format: {value}")
    parts = [javatext.parse_int(part) for part in (value[0:4], value[4:6], value[6:])]
    if any(part is None for part in parts):
        raise TranslationConversionError(f"Date must have YYYYMMDD format: {value}")
    year, month, day = parts
    try:
        datetime.date(year, month, day)
    except ValueError as error:
        raise TranslationConversionError(f"Invalid date {value}") from error
    return year * 10000 + month * 100 + day


def _java_time(value: str) -> int:
    """`GtfsTime.fromString`, as seconds since midnight.

    Hours run past 24, so only minutes and seconds are bounded; `fromHourMinuteSecond` rejects
    the rest.
    """
    match = _TIME_PATTERN.match(value)
    if match is None:
        raise TranslationConversionError(f"Time must have H:MM:SS, HH:MM:SS or HHH:MM:SS: {value}")
    hour, minute, second = (javatext.parse_int(group) for group in match.groups())
    if minute >= _MINUTES_PER_HOUR or second >= _SECONDS_PER_MINUTE:
        raise TranslationConversionError(f"Invalid time {value}")
    return hour * 3600 + minute * 60 + second


def _convert(field, value: str) -> object:
    """`wrapStringAccessorWithTypeConversion`, with Java's own parsers rather than ours.

    Four types are converted and everything else is compared as the string it already is. The
    typing stage's parsers are deliberately not reused: they are ASCII-only, matching upstream's
    *field* parsing, while these mirror `Integer.parseInt`, `GtfsDate.fromString` and
    `GtfsTime.fromString`, which differ on Unicode digits and on a `+` inside a date.

    An integer failure returns the miss sentinel, because upstream catches it. A date or time
    failure raises, because upstream does not.
    """
    if field is None:
        return value
    if field.type is FieldType.INTEGER:
        parsed = javatext.parse_int(value)
        return _UNCONVERTIBLE if parsed is None else parsed
    if field.type is FieldType.DATE:
        return _java_date(value)
    if field.type is FieldType.TIME:
        return _java_time(value)
    if field.type is FieldType.LANGUAGE_CODE:
        # `Locale.forLanguageTag` never throws, and no key column at the pin uses this type, so
        # nothing reaches it: the canonical form keeps it consistent with the language rules.
        return locales.canonical(value)
    return value
