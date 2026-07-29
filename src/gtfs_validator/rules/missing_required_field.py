"""The rule-layer sources of `missing_required_field`.

Four validators emit it, so all four live here: one module per notice code, whatever the number of
upstream sources. The engine emits the same code from stage 3 for any field
the schema marks @Required, and neither field below is marked that way, so for these
the rule layer is the only source.

**TransferStopIdsConditionalValidator.** Both `transfers.from_stop_id` and
`to_stop_id` are `@ConditionallyRequired`, a documentation marker that suppresses the
engine's automatic check. Two gates: a row whose `transfer_type` is absent is skipped
entirely, and an in-seat transfer needs neither id because the trips imply the stops.

**StopTimesGeographyIdPresenceValidator.** A stop time must name exactly one of
`stop_id`, `location_group_id` and `location_id`. Naming none reports `stop_id` as
missing; naming more than one is `forbidden_geography_id`, in its own module.
Measured: a stop time with none of the three reports `stop_id`.

**TransfersInSeatTransferTypeValidator.** An in-seat transfer, type 4 or 5, requires
`from_trip_id` and `to_trip_id`: the trips are how the transfer identifies which vehicle stays put.
This is the mirror of the stop-id branch above, which *skips* those types, and having only that half
was a gap for several cohorts. Found by a probe built for a different rule, which reported four
notices we did not.

**TranslationFieldAndReferenceValidator.** Two passes, and both report this code. The first
names `field_name`, `language` or `table_name` when a translations row omits one, and its
finding stops the validator: the other three translation codes then emit nothing for that
feed. The second names `record_id` or `record_sub_id` when the parent table's key columns call
for one the row does not carry, so a translation of stop_times.txt without a `record_sub_id`
is reported while one of stops.txt is not. Both measured.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import translations
from gtfs_validator.rules._shared.conditional_agency_id import (
    FARE_LEG_JOIN_RULES,
    rows_missing_stop_peer,
)
from gtfs_validator.rules.registry import file_rule

FILENAME = "transfers.txt"
STOP_TIMES = "stop_times.txt"
# A stop time must name exactly one of these.
GEOGRAPHY_FIELDS = ("stop_id", "location_group_id", "location_id")
# GtfsTransferType.IN_SEAT_TRANSFER_ALLOWED and IN_SEAT_TRANSFER_NOT_ALLOWED.
IN_SEAT_TYPES = (4, 5)
REQUIRED_IDS = ("from_stop_id", "to_stop_id")
# The mirror of REQUIRED_IDS: an in-seat transfer needs the trips instead.
REQUIRED_TRIP_IDS = ("from_trip_id", "to_trip_id")


def _missing(filename: str, row_number: int, field_name: str) -> Notice:
    return Notice(
        "missing_required_field",
        Severity.ERROR,
        {"filename": filename, "csvRowNumber": row_number, "fieldName": field_name},
    )


@file_rule(code="missing_required_field", severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    yield from _transfer_stop_ids(feed)
    yield from _stop_time_geography(feed)
    yield from _in_seat_trip_ids(feed)
    yield from _translations(feed)
    yield from _fare_leg_join_stops(feed)


def _fare_leg_join_stops(feed) -> Iterator[Notice]:
    """FareLegJoinRuleValidator: naming one stop end obliges the other.

    The fifth source of this code, found by sweeping every code in the manifest for upstream
    emitters rather than only checking new ones. The dispatcher above listed four and read like a
    complete set, which is the same shape that hid two sources of missing_recommended_field.
    """
    for row, absent in rows_missing_stop_peer(feed):
        yield Notice(
            "missing_required_field",
            Severity.ERROR,
            {
                "filename": FARE_LEG_JOIN_RULES,
                "csvRowNumber": row["_row_number"],
                "fieldName": absent,
            },
        )


def _transfer_stop_ids(feed) -> Iterator[Notice]:
    for row in feed.rows(FILENAME):
        transfer_type = row.get("transfer_type")
        # hasTransferType: a blank type is skipped rather than treated as 0.
        if transfer_type is None or transfer_type in IN_SEAT_TYPES:
            continue
        for field in REQUIRED_IDS:
            if row.get(field) is not None:
                continue
            yield Notice(
                "missing_required_field",
                Severity.ERROR,
                {
                    "filename": FILENAME,
                    "csvRowNumber": row["_row_number"],
                    "fieldName": field,
                },
            )


def _stop_time_geography(feed) -> Iterator[Notice]:
    """A stop time naming none of the three geography ids reports stop_id.

    Filtered in SQL: on a healthy feed this keeps nothing at all out of the largest
    table, so streaming every row to Python to drop it was a whole pass for no rows.
    """
    for row in feed.rows_where_all_null(STOP_TIMES, GEOGRAPHY_FIELDS):
        yield Notice(
            "missing_required_field",
            Severity.ERROR,
            {
                "filename": STOP_TIMES,
                "csvRowNumber": row["_row_number"],
                "fieldName": "stop_id",
            },
        )


def _in_seat_trip_ids(feed) -> Iterator[Notice]:
    """Both trip ids, for a transfer whose type says the passenger stays seated.

    A row with no transfer_type is skipped, as upstream's `hasTransferType` gate does, so a blank
    type is not read as 0.
    """
    # TransfersInSeatTransferTypeValidator injects stops and stop times as well as transfers, so a
    # failure in either skips it. Measured: with a failed stops.txt the jar reports no trip-id
    # notices and reading only transfers reported both.
    if feed.dependency_failed("stops.txt") or feed.dependency_failed(STOP_TIMES):
        return
    for row in feed.rows(FILENAME):
        if row.get("transfer_type") not in IN_SEAT_TYPES:
            continue
        for field in REQUIRED_TRIP_IDS:
            if row.get(field) is None:
                yield _missing(FILENAME, row["_row_number"], field)


def _translations(feed) -> Iterator[Notice]:
    """The two translations passes, in upstream's order.

    The first pass returning anything means the second never runs, which is why this is one
    function rather than two independent loops: the order is the behaviour.
    """
    rows = translations.rows_of(feed)
    missing = translations.missing_standard_fields(rows)
    if missing:
        for row_number, field in missing:
            yield _missing(translations.FILENAME, row_number, field)
        return
    for row in rows:
        # `hasFieldValue()`: present, not truthy, so an empty one skips the lookup too.
        if row.get(translations.FIELD_VALUE) is not None:
            continue
        parent = translations.parent_filename(row)
        keys = translations.key_columns(parent)
        if keys is None or feed.is_missing(parent):
            continue
        # Upstream joins the two checks with `||`, so a record_id whose presence is wrong
        # stops the row before record_sub_id is looked at. Checking both independently
        # reported three notices where the jar reports two.
        for field, expected in translations.presence_checks(keys):
            if (row.get(field) is not None) == expected:
                continue
            if expected:
                yield _missing(translations.FILENAME, row["_row_number"], field)
            break
