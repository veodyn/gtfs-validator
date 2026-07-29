"""StopTimeIncreasingDistanceValidator: a trip whose `shape_dist_traveled` stops rising.

A scan down each trip's stop times comparing every row with the one before it, where "before"
is by **stop_sequence**: the container indexes stop times by (trip_id, stop_sequence), so
file order never reaches the rule. Measured on a trip written 3, 1, 2, which the jar reports
as two decreases naming rows the file order would not have paired.

Equal counts. The comparison is `>=`, so a trip standing still between two stops is an error
and not merely a suspicious value.

The two ways a row leaves the scan are not symmetric, and the asymmetry is the whole reason
this file has a `continue` in one place and a plain guard in the other:

- **No stop_id**: the row is skipped *before* `prev` is assigned, so the next comparison
  reaches back past it. Upstream added that skip for flex feeds, where a stop time can name a
  location or a location group instead (issue 1882). Measured: a trip of 0, 100, 0.5 whose
  middle row has no stop_id draws nothing, because 0.5 is compared against 0.
- **No shape_dist_traveled**: the comparison is skipped but the row still becomes `prev`.
  Measured on a trip of 5, unset, 1, which draws **nothing**: the 1 is compared against the
  unset row rather than against the 5 two positions back. A trip of unset, 5, 1 cannot show
  this, since it reports the same single notice either way, and a review caught the first
  version of these tests claiming it could.

`shouldCallValidate` gates on both columns. Only one of the two can be observed: with no
stop_id column every row fails the presence test anyway, so the conjunct is here for fidelity
rather than for an effect a feed could show.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import multimap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import stop_time_trips
from gtfs_validator.rules.registry import file_rule

CODE = "decreasing_or_equal_stop_time_distance"
STOP_TIMES = "stop_times.txt"
DISTANCE = "shape_dist_traveled"
SEQUENCE = "stop_sequence"
GATE_COLUMNS = ("stop_id", DISTANCE)


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if not all(feed.has_column(STOP_TIMES, column) for column in GATE_COLUMNS):
        return

    # A batch of trips at a time, in the order the multimap yields its keys. That order is
    # chosen rather than the store's cheapest, because the notices have to come out in it and
    # above the 1,000-sample cap the order decides which of them survive.
    ids = multimap_order(stop_time_trips.trip_ids(feed))
    for trip_id, rows in stop_time_trips.stream_in_order(feed, ids):
        previous: dict | None = None
        for current in rows:
            # Before the assignment below, so the next row compares against `previous`.
            if current.get("stop_id") is None:
                continue
            if (
                previous is not None
                and previous.get(DISTANCE) is not None
                and current.get(DISTANCE) is not None
                and previous[DISTANCE] >= current[DISTANCE]
            ):
                yield Notice(
                    CODE,
                    Severity.ERROR,
                    {
                        "tripId": trip_id,
                        "stopId": current["stop_id"],
                        "csvRowNumber": current["_row_number"],
                        "shapeDistTraveled": current[DISTANCE],
                        "stopSequence": current.get(SEQUENCE),
                        "prevCsvRowNumber": previous["_row_number"],
                        "prevShapeDistTraveled": previous[DISTANCE],
                        "prevStopSequence": previous.get(SEQUENCE),
                    },
                )
            previous = current
