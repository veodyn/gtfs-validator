"""The trip-versus-shape comparison both TripAndShapeDistanceValidator codes share.

A trip whose last stop time claims more `shape_dist_traveled` than its shape's furthest point is
either mismeasured or attached to the wrong shape, and the *geographic* distance between those two
points decides which of the two codes says so.

Order is trips.txt file order, over `getEntities()`, with no map involved.

Four early returns, and the reasons differ:

- **No stop times** for the trip: nothing to compare.
- **The last stop time's stop is missing** from stops.txt: upstream returns rather than measuring,
  so a broken reference is left to `foreign_key_violation`. That is the opposite of
  `TransferDistanceValidator`, which measures an unresolvable stop from latitude 0.
- **No shape** under the trip's `shape_id`, which is also how a trip with no shape at all leaves:
  an unset id reads as `""` through the getter and finds nothing.
- **The shape's greatest distance is 0**, which also covers a shape whose points leave
  `shape_dist_traveled` unset, since an unset double reads as 0.

The distance is the `S2LatLng` haversine overload, not the `S2Point` one the transfer rules use.
Confirmed by value rather than by reading alone: the haversine reproduces the jar's
111.19510117719409 on the probe and the vector form gives 111.19510117700135.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.s2earth import distance_meters

TRIPS = "trips.txt"
STOP_TIMES = "stop_times.txt"
SHAPES = "shapes.txt"
STOPS = "stops.txt"
DISTANCE = "shape_dist_traveled"
SEQUENCE = "shape_pt_sequence"
# TripAndShapeDistanceValidator.DISTANCE_THRESHOLD, in metres.
DISTANCE_THRESHOLD_METERS = 11.1


def overrunning_trips(feed) -> Iterator[tuple[dict, dict]]:
    """Each trip claiming more distance than its shape, with the measured context.

    Reading all four tables is what reproduces the gate: the validator takes all four containers,
    so a failure in any of them silences both codes.
    """
    stops = _by_id(feed, STOPS, "stop_id")
    last_stop_times = _last_stop_times(feed)
    furthest = _furthest_shape_points(feed)
    for trip in feed.rows(TRIPS):
        trip_id = trip.get("trip_id")
        last = last_stop_times.get(trip_id)
        if last is None:
            continue
        stop = stops.get(last.get("stop_id"))
        if stop is None:
            continue
        # An unset shape_id reads as "" through the getter, which finds no shape unless one
        # really is named "". Not a presence test, though it behaves like one here.
        shape_point = furthest.get(trip.get("shape_id") or "")
        if shape_point is None:
            continue
        # An unset shape_dist_traveled reads as 0, so this guard covers a shape with no
        # distances at all as well as one that genuinely ends at 0.
        shape_distance = shape_point.get(DISTANCE) or 0.0
        if shape_distance == 0:
            continue
        trip_distance = last.get(DISTANCE) or 0.0
        if trip_distance <= shape_distance:
            continue
        yield (
            trip,
            {
                "tripId": trip_id,
                "shapeId": trip.get("shape_id") or "",
                "maxTripDistanceTraveled": trip_distance,
                "maxShapeDistanceTraveled": shape_distance,
                "geoDistanceToShape": distance_meters(
                    shape_point["shape_pt_lat"],
                    shape_point["shape_pt_lon"],
                    stop["stop_lat"],
                    stop["stop_lon"],
                ),
            },
        )


def _by_id(feed, filename: str, column: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for row in feed.rows(filename):
        key = row.get(column)
        if key is not None:
            rows.setdefault(key, row)
    return rows


def _last_stop_times(feed) -> dict[str, dict]:
    """Each trip's stop time with the highest stop_sequence.

    `byTripId(tripId).get(size - 1)` takes the last element of a list the container sorted by
    `@SequenceKey`, so it is the greatest sequence rather than the last row in the file, and
    among rows sharing the greatest sequence the *last in file order* wins, because the sort is
    stable. A review measured it: two rows at sequence 1, the far stop first and the near one
    second, put the jar in the below-threshold band and taking the first put us in the other.
    Both rules are exactly `rows_at_group_max`'s, so the pass over the largest table in the feed
    happens in SQL and only the one row per trip reaches Python.
    """
    return {
        row["trip_id"]: row
        for row in feed.rows_at_group_max(STOP_TIMES, "trip_id", "stop_sequence")
    }


def _furthest_shape_points(feed) -> dict[str, dict]:
    """Each shape's point with the greatest `shape_dist_traveled`, keeping the earlier on a tie.

    `Stream.max` replaces its candidate only on a strictly greater comparison, so two points at
    the same distance leave the first one holding. That decides which coordinates are measured.

    One group resident at a time, because a first version collected the whole of shapes.txt
    into a dict of lists: 3.45 million rows on a real feed, which is exactly the
    materialisation the store exists to avoid, and it survived every probe because no probe
    carries more than a few dozen shape points.
    """
    furthest: dict[str, dict] = {}
    for shape_id, points in feed.rows_grouped_by(SHAPES, "shape_id"):
        # `byShapeId` hands the validator a list already sorted by shape_pt_sequence, and
        # `Stream.max` keeps the first tied element *of that list*, not of the file. A review
        # measured the difference on a shape whose rows appear in descending sequence with equal
        # distances: taking the first tie in file order picked the wrong coordinates and moved the
        # notice into the other band.
        points.sort(key=lambda row: (row.get(SEQUENCE), row["_row_number"]))
        best = points[0]
        for point in points[1:]:
            if (point.get(DISTANCE) or 0.0) > (best.get(DISTANCE) or 0.0):
                best = point
        furthest[shape_id] = best
    return furthest
