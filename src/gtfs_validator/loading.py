"""Stages 2 to 4: read a table out of the archive, type its rows, and store them.

Split from `cli`, which owns the command line and the order the stages run in, when the two
together passed the file-size limit. The division is by responsibility: everything here is about
turning one file in the archive into rows in the store and notices about the attempt, and knows
nothing about arguments, reports or exit statuses.

`locations.geojson` is loaded by its own function rather than through the table path, mirroring
upstream's separate `GeoJsonFileLoader`: it is a @GtfsJson schema that the table generator skips.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.container import GEOJSON_FILE
from gtfs_validator.csvparse import parse_table
from gtfs_validator.error_ids import AppError, CarriedFailure
from gtfs_validator.geojson import UnreadableGeoJson
from gtfs_validator.geojson import parse as parse_geojson
from gtfs_validator.geojson.constants import FEATURE_SCHEMA
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.schema import Presence, TableSchema
from gtfs_validator.store import ROW_NUMBER_COLUMN, FeedStore
from gtfs_validator.table_status import TableLoad, TableStatus
from gtfs_validator.typing_stage import type_row


def _system_error(system_errors: NoticeContainer, filename: str, exc: Exception) -> None:
    """runtime_exception_in_loader_error, with upstream's three context fields.

    RuntimeExceptionInLoaderError carries filename, the exception's class name
    and its message; dropping the class name loses the only field that says what
    went wrong when the message is empty.

    An AppError reports through to_log_line rather than str, so the stable error
    ID and its structured context survive into the message. That is what the
    registry in error_ids.py is for, and E_TYPE_001 was reaching the report
    without its ID until this was fixed. The ID goes inside the message rather
    than into a fourth key so the notice's shape stays upstream's.
    """
    if isinstance(exc, CarriedFailure):
        # A worker pre-rendered both fields; see error_ids.carry.
        name, message = exc.class_name, exc.message
    else:
        name = type(exc).__name__
        message = exc.to_log_line() if isinstance(exc, AppError) else str(exc)
    system_errors.add(
        Notice(
            "runtime_exception_in_loader_error",
            Severity.ERROR,
            {
                "filename": filename,
                "exception": name,
                "message": message,
            },
        )
    )


def _required_columns(schema: TableSchema) -> tuple[str, ...]:
    """Columns whose absence draws missing_required_column.

    Two things count: a field declared @Required, and a field marked
    @RequiredColumn (transfers.transfer_type, rider_categories.is_default_fare_category)
    whose header must exist even though its values may be empty. Selecting only
    the first misses the required-column notice for the second.
    """
    return tuple(
        field.name
        for field in schema.fields
        if field.presence is Presence.REQUIRED or field.required_column
    )


def _typed_rows(
    schema: TableSchema,
    rows: Iterator[dict],
    notices: NoticeContainer,
    country_code: str,
    load: TableLoad,
) -> Iterator[dict]:
    """Type each row, dropping the ones that failed and recording that they did.

    A dropped row is not merely skipped: upstream marks the whole table
    UNPARSABLE_ROWS, which suppresses its key indices entirely. See table_status.
    """
    for row in rows:
        typed = type_row(schema, row, notices, country_code)
        if typed is None:
            load.fail(TableStatus.UNPARSABLE_ROWS)
            continue
        yield typed


# Deliberately empty, and a test asserts it stays that way.
#
# An absent recommended *column* is reported per row as missing_recommended_field by
# stage 3, which is what upstream does. `missing_recommended_column` itself is
# declared in upstream's deprecated package and constructed nowhere, so populating
# this map would make us emit a notice the jar cannot: a divergence introduced by a
# data change rather than a code change.
RECOMMENDED_COLUMNS: dict[str, tuple[str, ...]] = {}


def _unreadable_table(filename: str, notices: NoticeContainer) -> TableLoad:
    """What upstream reports for a table it listed but cannot open.

    Only a mac-wrapped zip reaches this. `GtfsZipFileInput` takes the wrapper
    folder out of the names it lists but not out of the names it reads, so
    `getFile` asks the archive for an entry it does not hold, Commons Compress
    answers with a null stream, univocity raises on it, and `CsvFileLoader` catches
    that as a parse failure and returns a container with INVALID_HEADERS.

    The context is measured off probe `macfeed` rather than reasoned about.
    `message` is "origin", the name of the null argument in univocity's own check,
    and the three indices are what a TextParsingException carries when it fails
    before reading a character.
    """
    notices.add(
        Notice(
            "csv_parsing_failed",
            Severity.ERROR,
            {
                "filename": filename,
                "charIndex": 0,
                "columnIndex": -1,
                "lineIndex": -1,
                "message": "origin",
                "parsedContent": "",
            },
        )
    )
    load = TableLoad()
    load.fail(TableStatus.INVALID_HEADERS)
    return load


def _load_table(
    feed,
    schema: TableSchema,
    store: FeedStore,
    notices: NoticeContainer,
    country_code: str,
) -> TableLoad:
    """Stream one table through parse, typing and storage without buffering it."""
    if not feed.is_readable(schema.filename):
        return _unreadable_table(schema.filename, notices)
    load = TableLoad()
    store.create_table(schema)
    rows = parse_table(
        feed,
        schema.filename,
        notices,
        required_columns=_required_columns(schema),
        recommended_columns=RECOMMENDED_COLUMNS.get(schema.filename, ()),
        known_columns=schema.column_names,
        load=load,
        max_chars_per_column=schema.max_chars_per_column,
    )
    # Rows that produced an ERROR are excluded from the store, matching
    # CsvFileLoader: they are not indexed and their entity validators do not run.
    store.insert_rows(schema, _typed_rows(schema, rows, notices, country_code, load))
    return load


def _load_geojson(feed: object, notices: NoticeContainer, store: FeedStore) -> TableLoad:
    """Parse locations.geojson, storing its features and reporting its load status.

    The features are stored now that a rule reads them: `duplicate_geography_id` compares feature
    ids against stops.txt and location_groups.txt. Their shape is declared in
    geojson.constants.FEATURE_SCHEMA rather than generated, because locations.geojson is a
    @GtfsJson schema that the table generator skips.

    The status matters on its own too: it is what suppresses missing_required_file for stops.txt.
    """
    load = TableLoad()
    # Listed but unreadable, which only a mac-wrapped zip produces. Upstream's
    # GeoJsonFileLoader swallows the failure where CsvFileLoader reports it:
    # measured on probe `macgeo`, the jar's report names locations.geojson in its
    # file listing and says nothing else about it, with no system error either.
    if not feed.is_readable(GEOJSON_FILE):
        load.fail(TableStatus.UNPARSABLE_ROWS)
        return load
    with feed.open_table(GEOJSON_FILE) as raw:
        # errors="replace" for the same reason csvparse uses it: upstream decodes
        # with onMalformedInput(REPLACE), so malformed bytes become U+FFFD rather
        # than aborting the read.
        text = raw.read().decode("utf-8-sig", errors="replace")
    # UnreadableGeoJson propagates: the caller turns it into a
    # runtime_exception_in_loader_error, which is what divergence 6 says we do where
    # upstream swallows the failure in a bare catch that only logs. The status is
    # set first so the table looks empty even though the load is also reported.
    store.create_table(FEATURE_SCHEMA)
    try:
        features = parse_geojson(text, notices, load)
    except UnreadableGeoJson:
        load.fail(TableStatus.UNPARSABLE_ROWS)
        raise
    load.columns = frozenset(FEATURE_SCHEMA.column_names)
    store.insert_rows(
        FEATURE_SCHEMA,
        ({**feature, ROW_NUMBER_COLUMN: feature["feature_index"]} for feature in features),
    )
    return load
