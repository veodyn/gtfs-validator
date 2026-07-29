"""LocationHasStopTimesValidator: a stop time at something that is not a platform.

A station, entrance, node or boarding area is part of the structure around a platform, not a
place a trip calls at, so a stop time naming one is an error. The counterpart is
`stop_without_stop_time`, which fires when a platform has none.

The reported stop time is `stopTimes.get(0)`, the earliest row naming the location in file
order, so a station named by three stop times reports the first.

Skipped when any of the validator's three containers failed, as its counterpart is: the
two notices come from one upstream validator and cannot be suppressed independently.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import STOP, location_type_of
from gtfs_validator.rules._shared.stop_time_usage import usage_of
from gtfs_validator.rules.registry import file_rule

CODE = "location_with_unexpected_stop_time"

# Upstream injects these containers, and a failure in any of them skips the validator.
DEPENDENCIES = ("stops.txt", "stop_times.txt", "location_group_stops.txt")


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if any(feed.dependency_failed(name) for name in DEPENDENCIES):
        return
    first_rows = usage_of(feed).first_row_by_stop
    for row in feed.rows("stops.txt"):
        stop_id = row.get("stop_id")
        if stop_id is None or location_type_of(row) == STOP:
            continue
        stop_time_row = first_rows.get(stop_id)
        if stop_time_row is None:
            continue
        yield Notice(
            CODE,
            Severity.ERROR,
            {
                "csvRowNumber": row["_row_number"],
                "stopId": stop_id,
                "stopName": row.get("stop_name") or "",
                "stopTimeCsvRowNumber": stop_time_row,
            },
        )
