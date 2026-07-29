"""Feed builders for BlockTripsWithOverlappingStopTimesValidator.

Shared rather than copied because the rule reads four tables, so a test that builds three of
them by hand is mostly scaffolding. Same reason `fasttravel.py` exists next door.
"""

from __future__ import annotations

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CODE = "block_trips_with_overlapping_stop_times"
CTX = Context(date=datetime.date(2026, 6, 1), country_code="US")

# 08:00:00 and friends as seconds since midnight, which is how the store holds a GtfsTime.
H8, H9, H10, H11, H12 = 28800, 32400, 36000, 39600, 43200
MINUTE = 60


def trip(number, trip_id, block_id="B1", service_id="WEEK"):
    return {
        "_row_number": number,
        "trip_id": trip_id,
        "route_id": "R1",
        "service_id": service_id,
        "block_id": block_id,
    }


def stop_times(trip_id, first, last, *, first_row=2):
    """Two stop times for a trip, each an (arrival, departure) pair. None leaves the field unset."""
    return [
        {
            "_row_number": first_row + index,
            "trip_id": trip_id,
            "stop_id": f"S{index + 1}",
            "stop_sequence": index + 1,
            "arrival_time": arrival,
            "departure_time": departure,
        }
        for index, (arrival, departure) in enumerate((first, last))
    ]


WEEKDAYS = {
    "monday": 1,
    "tuesday": 1,
    "wednesday": 1,
    "thursday": 1,
    "friday": 1,
    "saturday": 0,
    "sunday": 0,
}


def calendar(service_id="WEEK", **days):
    pattern = {**WEEKDAYS, **days}
    return {
        "_row_number": 2,
        "service_id": service_id,
        **pattern,
        "start_date": 20260601,
        "end_date": 20260831,
    }


def fire(trips, times, *, calendars=None, unindexable=frozenset()):
    registry.load_rules()
    view = FakeFeed(
        {
            "trips.txt": trips,
            "stop_times.txt": times,
            "calendar.txt": calendars if calendars is not None else [calendar()],
            "calendar_dates.txt": [],
        },
        unindexable=unindexable,
    )
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(view, CTX)]


def pairs(notices):
    return [(n["tripIdA"], n["tripIdB"]) for n in notices]


