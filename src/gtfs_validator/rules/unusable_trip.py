"""TripUsabilityValidator: a trip a rider cannot actually take.

One stop time is not a journey, so the threshold is `<= 1` rather than `== 0`: a
trip with a single stop_times row is reported alongside one with none.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule

MIN_USABLE_STOP_TIMES = 2


@file_rule(code="unusable_trip", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # Counted per trip in SQL rather than collected or streamed: stop_times.txt is
    # the largest table in a feed and only the tally per trip is needed.
    counts: dict[str, int] = dict(feed.group_counts("stop_times.txt", "trip_id"))
    for trip in feed.rows("trips.txt"):
        trip_id = trip.get("trip_id")
        if counts.get(trip_id, 0) >= MIN_USABLE_STOP_TIMES:
            continue
        yield Notice(
            "unusable_trip",
            Severity.WARNING,
            {"csvRowNumber": trip["_row_number"], "tripId": trip_id},
        )
