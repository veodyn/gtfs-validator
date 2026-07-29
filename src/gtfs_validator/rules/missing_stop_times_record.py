"""StopTimesRecordValidator: a flex trip served by one stop time where two are required.

Travel within a location group or a GeoJSON location needs two stop_times rows naming that
place, one for boarding and one for alighting. A trip whose only stop time carries a complete
window and must-phone for both pickup and drop-off has half of that.

Four conditions, and each is read against what the generated entity returns rather than
against what the CSV holds: an unset `pickup_type` is `REGULAR`, not an absence, so a feed
leaving both type columns blank is never reported. The two location keys go the other way and
are always present, `""` where unset, because upstream passes the getters rather than nulls.

A FileValidator, so it reads the gated `rows()`: one unparsable row anywhere in
stop_times.txt leaves upstream a container holding no entities and this code says nothing,
while the per-entity window codes still report the clean rows beside it. Measured on a pair of
feeds differing only in that row.

`shouldCallValidate` wants all four columns, not one of them, so a feed declaring the windows
but no pickup_type never runs this validator at all. That gate cannot change the output, since
an undeclared pickup_type reads as REGULAR and fails the predicate anyway. It is here because
it decides whether the table is *scanned*, and this is the one rule in the cohort whose cost
is a pass over the largest file in a feed.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import windows
from gtfs_validator.rules.registry import file_rule, scan_rule

CODE = "missing_stop_times_record"
STOP_TIMES = "stop_times.txt"
PICKUP_TYPE = "pickup_type"
DROP_OFF_TYPE = "drop_off_type"
REQUIRED_COLUMNS = (*windows.WINDOW_COLUMNS, PICKUP_TYPE, DROP_OFF_TYPE)
# GtfsPickupDropOff.MUST_PHONE.
MUST_PHONE = 2


class _Consumer:
    """One shared pass for the counts; a second pass only when a lone trip exists.

    The count a row needs is over rows that come after it, so one pass cannot
    decide. Only the per-trip counts are held, one integer per trip. Upstream is
    free to do this in one pass because its byTripId multimap already holds a
    reference to every row; this build has no such table in memory and must not
    build one. Keeping the qualifying rows instead would hold the whole table on
    a feed where every stop time qualifies, which a flex feed of one trip does.
    """

    def __init__(self, feed) -> None:
        self._feed = feed
        self._counts: dict[str, int] = {}

    def row(self, row: dict) -> None:
        trip_id = row.get("trip_id") or ""
        self._counts[trip_id] = self._counts.get(trip_id, 0) + 1

    def finish(self) -> Iterator[Notice]:
        counts = self._counts
        if 1 not in counts.values():
            # No lone trip anywhere: the emitting pass cannot yield, so skip it.
            return
        # File order, measured: three lone flex trips written in descending id order are
        # reported in that same order, so the container yields entities as loaded rather
        # than sorted.
        for row in self._feed.rows(STOP_TIMES):
            trip_id = row.get("trip_id") or ""
            if counts[trip_id] != 1 or not _qualifies(row):
                continue
            yield Notice(
                CODE,
                Severity.ERROR,
                {
                    "csvRowNumber": row["_row_number"],
                    "tripId": trip_id,
                    "locationGroupId": row.get("location_group_id") or "",
                    "locationId": row.get("location_id") or "",
                },
            )


@scan_rule(code=CODE, table=STOP_TIMES)
def scan(feed, ctx: Context) -> _Consumer | None:
    """The hub factory: None unless the header carries all four columns.

    The header test's interaction with the failed-table gate does not matter:
    `has_column` reads the load's recorded header, so a table that failed to load
    still answers about the columns it declared, and a table that declared them
    goes on to `rows()` and raises. Where the two gates disagree they both mean
    "no notices".
    """
    if not all(feed.has_column(STOP_TIMES, column) for column in REQUIRED_COLUMNS):
        return None
    return _Consumer(feed)


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    """The sequential path, on the same consumer the hub feeds."""
    consumer = scan(feed, ctx)
    if consumer is None:
        return
    for row in feed.rows(STOP_TIMES):
        consumer.row(row)
    yield from consumer.finish()


def _qualifies(row: dict) -> bool:
    return (
        windows.has_both_windows(row)
        and row.get("pickup_type") == MUST_PHONE
        and row.get("drop_off_type") == MUST_PHONE
    )
