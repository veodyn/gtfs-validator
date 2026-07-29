"""Feed builders for the two StopTimeTravelSpeedValidator codes.

Shared rather than copied because the rules read four tables, and a test that builds three of
them by hand is mostly scaffolding. The latitudes are the probe's: one meridian, so every
distance is a latitude difference, and 0.05 degrees is 5.559755058873851 km against the
10 km far-stop threshold while 0.10 degrees is 11.119510117748408 km.
"""

from __future__ import annotations

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")

CONSECUTIVE = "fast_travel_between_consecutive_stops"
FAR = "fast_travel_between_far_stops"

# The probe's stops, and the distances between them in km as the jar reported them.
NEAR_KM = 5.559755058873851
FAR_KM = 11.119510117748408
# A to a stop at latitude 0, longitude 0, which upstream measures rather than skipping.
ORIGIN_KM = 8652.115181854942
LATITUDES = {"A": 40.0, "B": 40.05, "C": 40.1}
LONGITUDE = -74.0

# 08:00:00 and the offsets the probe uses, in seconds since midnight.
T0800 = 28800
BUS = 3
RAIL = 2


def stop(stop_id, number, latitude=None, *, longitude=LONGITUDE, name=None, parent=None):
    """One stops.txt row. A stop with no latitude borrows its parent's, or resolves nowhere.

    The longitude defaults to the probe's meridian so that a distance is a latitude
    difference. The origin stop is the one row that needs its own, and giving every stop the
    meridian silently put it 4,447 km away instead of 8,652.
    """
    row = {
        "_row_number": number,
        "stop_id": stop_id,
        "stop_name": name if name is not None else f"Stop {stop_id}",
    }
    if latitude is not None:
        row["stop_lat"] = latitude
        row["stop_lon"] = longitude
    if parent is not None:
        row["parent_station"] = parent
    return row


def stops(*ids, extra=()):
    """The named stops from `LATITUDES`, numbered from 2, plus any rows given whole."""
    rows = [stop(stop_id, number, LATITUDES[stop_id]) for number, stop_id in enumerate(ids, 2)]
    return [*rows, *extra]


def route(route_id, number, route_type=BUS):
    return {"_row_number": number, "route_id": route_id, "route_type": route_type}


def trip(trip_id, number, route_id="R1"):
    return {"_row_number": number, "trip_id": trip_id, "route_id": route_id}


def stop_time(number, trip_id, sequence, stop_id, arrival, departure=None):
    """One stop_times row. `departure` defaults to the arrival, as a timetable usually has."""
    return {
        "_row_number": number,
        "trip_id": trip_id,
        "stop_id": stop_id,
        "stop_sequence": sequence,
        "arrival_time": arrival,
        "departure_time": arrival if departure is None else departure,
    }


def chain(trip_id="TI", *, first_row=22, count=11):
    """The probe's eleven stops about 1.22 km apart, all timed at 08:00:00.

    Every hop is slow enough to pass the consecutive check and the span is not, which is the
    only way to reach the far-stop code without the consecutive one firing first.
    """
    rows = [stop(f"P{index}", 20 + index, 40.0 + index * 0.011) for index in range(count)]
    times = [
        stop_time(first_row + index, trip_id, index + 1, f"P{index}", T0800)
        for index in range(count)
    ]
    return rows, times


def feed(stop_times, *, trips=None, routes=None, stop_rows=None, unindexable=frozenset()):
    """A feed with sensible defaults for the three tables a test is not varying."""
    return FakeFeed(
        {
            "stop_times.txt": stop_times,
            "trips.txt": trips if trips is not None else [trip("T1", 2)],
            "routes.txt": routes if routes is not None else [route("R1", 2)],
            "stops.txt": stop_rows if stop_rows is not None else stops("A", "B", "C"),
        },
        unindexable=unindexable,
    )


def fire(code, stop_times, **kwargs):
    registry.load_rules()
    view = feed(stop_times, **kwargs)
    return [notice.context for notice in registry.FILE_REGISTRY[code].func(view, CTX)]
