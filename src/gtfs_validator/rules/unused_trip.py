"""TripUsageValidator: a trip nothing stops at.

A trip with no stop_times row is unusable, and this is the plainest form of that: no times
at all, rather than the single-stop case `unusable_trip` reports.

Upstream guards with a set of reported trip ids, so a trip_id appearing twice is reported
once, and that guard is reachable: a duplicate trip_id draws `duplicate_key` and **both**
rows still reach the container, measured. Without the guard a duplicated unused trip would
be reported twice.

TripUsageValidator takes both containers, so a failed or absent stop_times.txt stops it
running rather than making every trip unused. Measured: with no stop_times.txt at all the jar
reports nothing here, and a header-only one reports every trip.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.stop_time_usage import usage_of
from gtfs_validator.rules.registry import file_rule

CODE = "unused_trip"

# Upstream injects these containers, and a failure in any of them skips the validator.
DEPENDENCIES = ("trips.txt", "stop_times.txt")


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if any(feed.dependency_failed(name) for name in DEPENDENCIES):
        return
    used = usage_of(feed).trips
    reported: set[str] = set()
    for row in feed.rows("trips.txt"):
        trip_id = row.get("trip_id")
        if trip_id is None or trip_id in reported:
            continue
        reported.add(trip_id)
        if trip_id in used:
            continue
        yield Notice(
            CODE,
            Severity.WARNING,
            {"tripId": trip_id, "csvRowNumber": row["_row_number"]},
        )
