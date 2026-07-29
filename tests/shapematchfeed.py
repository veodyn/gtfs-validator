"""Feed builders for the four ShapeToStopMatchingValidator codes.

One builder for all four because the rules share one pass and the sharing is itself behaviour: a
test that the user-distance code stays quiet for a stop the geo pass named has to drive both
through the same feed.

Coordinates are the probe feeds' own, so an expectation here can be checked against a jar run
rather than only against this port. `shapematch/sm1.zip` and its siblings in the scratchpad are
those feeds; the geometry is repeated here rather than the zip being read, so the tests need no
fixture file on disk.
"""

from __future__ import annotations

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 1), country_code="US")

TOO_FAR = "stop_too_far_from_shape"
TOO_FAR_USER_DISTANCE = "stop_too_far_from_shape_using_user_distance"
TOO_MANY_MATCHES = "stop_has_too_many_matches_for_shape"
OUT_OF_ORDER = "stops_match_shape_out_of_order"

# A bus route, so the large-station multiplier stays out of it. Route type 2 is the rail case.
BUS = 3
RAIL = 2


def route(route_type=BUS, route_id="R1"):
    return {"_row_number": 2, "route_id": route_id, "route_type": route_type}


def trip(trip_id="T1", shape_id="SH1", route_id="R1", number=2):
    return {
        "_row_number": number,
        "trip_id": trip_id,
        "route_id": route_id,
        "shape_id": shape_id,
        "service_id": "WEEK",
    }


def stop(stop_id, name, latitude, longitude, number=2, **extra):
    return {
        "_row_number": number,
        "stop_id": stop_id,
        "stop_name": name,
        "stop_lat": latitude,
        "stop_lon": longitude,
        **extra,
    }


def stops(*entries):
    """Stops numbered from row 2 in the order given."""
    return [
        stop(
            entry[0],
            entry[1],
            entry[2],
            entry[3],
            number=2 + index,
            **(entry[4] if len(entry) > 4 else {}),
        )
        for index, entry in enumerate(entries)
    ]


def stop_times(trip_id, *entries, start_row=2):
    """One row per (stop_id, shape_dist_traveled) pair, sequenced from 1.

    A distance of None means the column was blank on that row, which is not the same as zero:
    zero is a present value that still fails `hasUserDistance`, and blank is what a feed without
    the column carries.
    """
    rows = []
    for index, entry in enumerate(entries):
        stop_id, distance = entry if isinstance(entry, tuple) else (entry, None)
        row = {
            "_row_number": start_row + index,
            "trip_id": trip_id,
            "stop_id": stop_id,
            "stop_sequence": index + 1,
        }
        if distance is not None:
            row["shape_dist_traveled"] = distance
        rows.append(row)
    return rows


def shape(*points, shape_id="SH1", start_row=2):
    """Shape points from (lat, lon) or (lat, lon, distance) tuples, sequenced from 1."""
    rows = []
    for index, point in enumerate(points):
        row = {
            "_row_number": start_row + index,
            "shape_id": shape_id,
            "shape_pt_lat": point[0],
            "shape_pt_lon": point[1],
            "shape_pt_sequence": index + 1,
        }
        if len(point) > 2:
            row["shape_dist_traveled"] = point[2]
        rows.append(row)
    return rows


def feed(*, stops_rows, trips_rows, times_rows, shape_rows, routes_rows=None):
    return FakeFeed(
        {
            "stops.txt": stops_rows,
            "trips.txt": trips_rows,
            "stop_times.txt": times_rows,
            "shapes.txt": shape_rows,
            "routes.txt": routes_rows if routes_rows is not None else [route()],
        }
    )


def fire(code, view):
    registry.load_rules()
    return [notice.context for notice in registry.FILE_REGISTRY[code].func(view, CTX)]


def all_codes(view):
    """Every code this validator produced, in emission order, for a whole-pass assertion."""
    from gtfs_validator.rules._shared.stop_to_shape_problems import problems

    return [code for code, _ in problems(view)]


# The sm1 geometry: a straight shape along one parallel with a stop 333 m north of its midpoint.
FAR_SHAPE = ((40.0, -74.0), (40.0, -73.995), (40.0, -73.99))
FAR_STOPS = (
    ("S1", "First", 40.0, -74.0),
    ("S2", "Far", 40.003, -73.995),
    ("S3", "Last", 40.0, -73.99),
)
NEAR_STOPS = (
    ("S1", "First", 40.0, -74.0),
    ("S2", "Near", 40.0005, -73.995),
    ("S3", "Last", 40.0, -73.99),
)


def far_feed(
    stop_entries=FAR_STOPS, distances=(None, None, None), route_type=BUS, shape_points=None
):
    """The too-far probe, parameterized on the three things its variants change."""
    points = FAR_SHAPE if shape_points is None else shape_points
    return feed(
        stops_rows=stops(*stop_entries),
        trips_rows=[trip()],
        times_rows=stop_times(
            "T1",
            ("S1", distances[0]),
            ("S2", distances[1]),
            ("S3", distances[2]),
        ),
        shape_rows=shape(*points),
        routes_rows=[route(route_type)],
    )
