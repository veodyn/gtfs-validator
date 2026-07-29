"""TimepointTimeValidator, second branch: an exact timepoint with no time.

A stop time flagged as an exact timepoint must carry both an arrival and a departure,
so one missing both draws two notices. Measured: the row with `timepoint` 1 and
neither time reports arrival_time and departure_time separately.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.timepoints import EXACT, STOP_TIMES, TIMEPOINT, declares_timepoint
from gtfs_validator.rules.registry import file_rule, scan_rule

TIME_FIELDS = ("arrival_time", "departure_time")


class _Consumer:
    def row(self, row: dict) -> list[Notice] | None:
        if row.get(TIMEPOINT) != EXACT:
            return None
        return [
            Notice(
                "stop_time_timepoint_without_times",
                Severity.ERROR,
                {
                    "csvRowNumber": row["_row_number"],
                    "tripId": row.get("trip_id"),
                    "stopSequence": row.get("stop_sequence"),
                    "specifiedField": field,
                },
            )
            for field in TIME_FIELDS
            if row.get(field) is None
        ]

    def finish(self) -> Iterator[Notice]:
        return iter(())


@scan_rule(code="stop_time_timepoint_without_times", table=STOP_TIMES)
def scan(feed, ctx: Context) -> _Consumer | None:
    """The hub factory: None when the header never declares `timepoint`."""
    if not declares_timepoint(feed):
        return None
    return _Consumer()


@file_rule(code="stop_time_timepoint_without_times", severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    """The sequential path, on the same consumer the hub feeds."""
    consumer = scan(feed, ctx)
    if consumer is None:
        return
    for row in feed.rows(STOP_TIMES):
        yield from consumer.row(row) or ()
    yield from consumer.finish()
