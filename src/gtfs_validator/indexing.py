"""Stage 4: primary key uniqueness and single-row cardinality.

Both checks are SQL rather than Python loops, which is the reason the store is a
database at all. Duplicate detection groups inside SQLite and pulls back only the
offending key groups, so memory stays proportional to the number of duplicates
rather than to the table.

Duplicate-key semantics are transliterated from TableContainerIndexGenerator:

  * A single-column key skips rows whose key is null (upstream's `if (!hasKey)
    continue`). A multi-column key keeps null parts, because the CompositeKey
    includes them, so two rows sharing a non-null first component and both-null
    optional parts do collide.
  * A multi-column key compares *type defaults*, not nulls. `CompositeKey.builder()`
    is fed the typed getters with no presence guard, and an unset int reads 0 while
    an unset GtfsTime reads 00:00:00, so a blank transfer_count collides with an
    explicit 0. Measured on `tcfeed`, where the jar reports a duplicate between rows
    2 and 6 that grouping nulls separately does not find.
  * Every row after the first in a group is its own notice, paired with the
    first row. Three rows sharing a key produce two notices, not one.
  * fieldName1 / fieldValue1 come from the **first** row of the group, not the
    offending one: upstream calls `key.getDefinedKeys(oldEntity)` and
    `getDefinedValues(oldEntity)`. On `tcfeed` the notice names all three key
    columns and reads "L1,L1,0" because row 2 sets transfer_count explicitly, while
    the offending row 6 leaves it blank. No fieldName2 is ever sent; the
    multi-column constructor takes only one name/value pair.
"""

from __future__ import annotations

from collections.abc import Mapping

from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.schema import FieldType, TableSchema
from gtfs_validator.store import ROW_NUMBER_COLUMN, FeedStore, quote_identifier
from gtfs_validator.table_status import TableLoad

# The value an unset field reads as through its typed getter, which is what the
# CompositeKey compares. Numbers and times default to zero; every string-like type
# defaults to "". A DATE has no reachable default: `calendar_dates.date` is the only
# DATE in any composite key and it is required, so an unset one fails typing and the
# row never reaches this stage.
_ZERO_DEFAULT_TYPES = frozenset(
    {
        FieldType.INTEGER,
        FieldType.FLOAT,
        FieldType.DECIMAL,
        FieldType.TIME,
        FieldType.LATITUDE,
        FieldType.LONGITUDE,
        FieldType.CURRENCY_AMOUNT,
        FieldType.ENUM,
    }
)


def _key_default(field_type: FieldType) -> str:
    """The SQL literal for what an unset key column compares as."""
    return "0" if field_type in _ZERO_DEFAULT_TYPES else "''"


def _render_key_value(field_type: FieldType, value: object) -> object:
    """Render a stored key value the way upstream's entity getter would.

    The generated CompositeKey joins `a.toString() + "," + b.toString()` over the
    *typed* entity fields, so the notice carries GtfsTime.toHHMMSS rather than the
    store's seconds-since-midnight. DATE needs no conversion: GtfsDate.toString is
    toYYYYMMDD, which is exactly how the store holds it.
    """
    if field_type is FieldType.TIME and isinstance(value, int):
        hours, remainder = divmod(value, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return value


def _duplicate_context(
    schema: TableSchema, key_values: list, first_row: int, new_row: int
) -> dict[str, object]:
    key = schema.primary_key
    types = {field.name: field.type for field in schema.fields}
    defined = [
        (name, _render_key_value(types[name], value))
        for name, value in zip(key, key_values, strict=True)
        if value is not None
    ]
    if not defined:
        # Upstream reduces over the defined values, and reducing an empty list
        # yields null rather than an empty string. The name join still yields "".
        field_name = ""
        field_value = None
    elif len(defined) == 1:
        # A lone defined value is sent raw, matching upstream's reduce, which
        # returns the single element rather than a joined string.
        field_name, field_value = defined[0]
    else:
        field_name = ",".join(name for name, _ in defined)
        field_value = ",".join(str(value) for _, value in defined)
    return {
        "filename": schema.filename,
        "oldCsvRowNumber": first_row,
        "newCsvRowNumber": new_row,
        "fieldName1": field_name,
        "fieldValue1": field_value,
    }


def _check_duplicate_keys(store: FeedStore, schema: TableSchema, notices: NoticeContainer) -> None:
    key = schema.primary_key
    if not key:
        return
    table = quote_identifier(schema.filename)
    single_column = len(key) == 1
    # A single-column null key is skipped entirely. A composite key keeps nulls.
    where = f"WHERE {quote_identifier(key[0])} IS NOT NULL " if single_column else ""

    # Group on the value each column *compares* as, which for a composite key means
    # substituting the type default an unset field reads through its getter. Grouping the
    # raw columns instead put a blank transfer_count in a different group from an explicit
    # 0 and missed a duplicate the jar reports.
    types = {field.name: field.type for field in schema.fields}
    grouped_on = ", ".join(
        f"COALESCE({quote_identifier(name)}, {_key_default(types[name])})"
        if not single_column
        else quote_identifier(name)
        for name in key
    )
    # The notice describes the group's *first* row, so its raw values have to come back
    # too: FIRST_VALUE over the same partition, ordered by row number.
    first_values = ", ".join(
        f"FIRST_VALUE({quote_identifier(name)}) OVER "
        f"(PARTITION BY {grouped_on} ORDER BY {ROW_NUMBER_COLUMN}) AS {quote_identifier('first_' + name)}"
        for name in key
    )

    # One window-function pass names, for every row, the first row sharing its key
    # (PARTITION BY groups nulls together, like GROUP BY). Every row past the first
    # in a group is an offender. This streams offenders directly rather than
    # re-querying the table once per duplicate group, which was O(rows x groups).
    inner = (
        f"SELECT {first_values}, {ROW_NUMBER_COLUMN} AS row_number, "  # noqa: S608 - checked identifiers
        f"MIN({ROW_NUMBER_COLUMN}) OVER (PARTITION BY {grouped_on}) AS first_row "
        f"FROM {table} {where}"
    )
    selected = ", ".join(quote_identifier("first_" + name) for name in key)
    offenders = store.query(
        f"SELECT {selected}, row_number, first_row FROM ({inner}) "  # noqa: S608 - checked identifiers
        # Source-row order, not group order. Upstream reports each offending row
        # as the loader reaches it, so interleaved groups stay interleaved.
        # Samples export in insertion order and cap at 1,000, so ordering by the
        # group's first row would export a different set of samples past the cap.
        f"WHERE row_number > first_row ORDER BY row_number"
    )
    for offender in offenders:
        key_values = [offender["first_" + name] for name in key]
        notices.add(
            Notice(
                "duplicate_key",
                Severity.ERROR,
                _duplicate_context(
                    schema, key_values, offender["first_row"], offender["row_number"]
                ),
            )
        )


def _check_cardinality(store: FeedStore, schema: TableSchema, notices: NoticeContainer) -> None:
    if not schema.single_row:
        return
    count = store.count(schema.filename)
    if count > 1:
        notices.add(
            Notice(
                "more_than_one_entity",
                Severity.WARNING,
                {"filename": schema.filename, "entityCount": count},
            )
        )


def check_indexes(
    store: FeedStore,
    schemas: dict[str, TableSchema],
    notices: NoticeContainer,
    loads: Mapping[str, TableLoad] | None = None,
) -> None:
    """Check keys and cardinality for every table that loaded cleanly.

    A table with a bad header or a single unparsable row is skipped outright,
    because upstream builds no indices for it: CsvFileLoader returns a container
    for the failed status instead of calling createContainerForHeaderAndEntities,
    which is where setupIndices runs. Filtering the bad rows out and indexing the
    rest would report a duplicate_key the jar never emits. See table_status.

    A table with no recorded load is indexed, so callers that only exercise the
    store keep working.
    """
    for filename, schema in sorted(schemas.items()):
        if not store.has_table(filename):
            continue
        load = (loads or {}).get(filename)
        if load is not None and not load.is_indexable:
            continue
        _check_duplicate_keys(store, schema, notices)
        _check_cardinality(store, schema, notices)
