"""TripWithShapeDistTraveledButNoShapeDistancesValidator: distances on one side only.

A trip whose stop times measure distance along the shape needs a shape that measures it too, or the
two cannot be compared. The check is asymmetric on purpose: **one** stop time carrying
shape_dist_traveled is enough to expect it, while **every** shape point must carry it to satisfy
the expectation.

Four ways out before the notice, all of them upstream's: no stop time on the trip carries a
distance, the trip names no shape, the shape it names has no points, or every point has a distance.
The reported stop time is the first one carrying a distance **in stop_sequence order**, not in file
order: upstream reads `byTripIdMap()`, which sorts each trip's stop times by sequence. Measured on a
trip whose sequence 20 is on row 2 and whose sequence 10 is on row 3, where the jar reports row 3.

Gated on stop_times.txt declaring shape_dist_traveled, which is a header test.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import multimap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule, scan_rule

CODE = "trip_with_shape_dist_traveled_but_no_shape_distances"
TRIPS = "trips.txt"
STOP_TIMES = "stop_times.txt"
SHAPES = "shapes.txt"
DISTANCE = "shape_dist_traveled"


class _Consumer:
    """The stop_times pass aggregates; shapes and trips stream at finish.

    Aggregates rather than the rows: the first stop time per trip that carries a
    distance, and whether every point of a shape carries one. Both are bounded by
    trips and shapes, where indexing stop_times.txt would hold the largest table
    in the feed.
    """

    def __init__(self, feed) -> None:
        self._feed = feed
        # Keyed by the lowest stop_sequence rather than the first row seen, because the
        # container is sorted by sequence and a feed may list a trip's stop times out
        # of order.
        self._best: dict[str, tuple[int, int]] = {}

    def row(self, row: dict) -> None:
        trip_id = row.get("trip_id")
        if trip_id is None or row.get(DISTANCE) is None:
            return
        sequence = row.get("stop_sequence")
        if sequence is None:
            return
        candidate = (sequence, row["_row_number"])
        if trip_id not in self._best or candidate < self._best[trip_id]:
            self._best[trip_id] = candidate

    def finish(self) -> Iterator[Notice]:
        feed = self._feed
        first_with_distance = {trip_id: row for trip_id, (_, row) in self._best.items()}
        if not first_with_distance:
            return

        complete_shapes: dict[str, bool] = {}
        for point in feed.rows(SHAPES):
            shape_id = point.get("shape_id")
            if shape_id is None:
                continue
            has_distance = point.get(DISTANCE) is not None
            complete_shapes[shape_id] = complete_shapes.get(shape_id, True) and has_distance

        # HashMap order over the trip ids, because upstream iterates byTripIdMap: above the
        # 1,000-sample cap the order decides which notices a report keeps.
        trips = {
            row.get("trip_id"): row for row in feed.rows(TRIPS) if row.get("trip_id") is not None
        }
        for trip_id in multimap_order(trips):
            trip = trips[trip_id]
            stop_time_row = first_with_distance.get(trip_id)
            shape_id = trip.get("shape_id")
            if stop_time_row is None or not shape_id:
                continue
            # A shape nobody defined is a broken reference, not this notice.
            if complete_shapes.get(shape_id, True):
                continue
            yield Notice(
                CODE,
                Severity.INFO,
                {
                    "tripCsvRowNumber": trip["_row_number"],
                    "tripId": trip_id,
                    "shapeId": shape_id,
                    "stopTimeCsvRowNumber": stop_time_row,
                },
            )


@scan_rule(code=CODE, table=STOP_TIMES)
def scan(feed, ctx: Context) -> _Consumer | None:
    """The hub factory: None unless stop_times.txt declares shape_dist_traveled."""
    if not feed.has_column(STOP_TIMES, DISTANCE):
        return None
    return _Consumer(feed)


@file_rule(code=CODE, severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    """The sequential path, on the same consumer the hub feeds."""
    consumer = scan(feed, ctx)
    if consumer is None:
        return
    for row in feed.rows(STOP_TIMES):
        consumer.row(row)
    yield from consumer.finish()
