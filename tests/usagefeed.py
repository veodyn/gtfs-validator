"""Feed fixtures shared by the rule tests that were one file until they were three.

`TABLES` mirrors `usefeed`, the probe the usage rules were measured on: its stop_times.txt is
deliberately untidy, with one trip's rows split by another trip's, one trip's stop_sequence
running backwards, one stop time naming a station and one naming a location group.

Everything here is a fixture, not an assertion. The measured expectations live beside the
tests that assert them, so a number can be read next to the probe it came from.
"""

from __future__ import annotations

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")

STOP, STATION, ENTRANCE = 0, 1, 2


def stop(number, stop_id, name, location_type=STOP, parent=None):
    return {
        "_row_number": number,
        "stop_id": stop_id,
        "stop_name": name,
        "location_type": location_type,
        "parent_station": parent,
    }


def stop_time(number, trip_id, stop_id, sequence, group=None):
    return {
        "_row_number": number,
        "trip_id": trip_id,
        "stop_id": stop_id,
        "stop_sequence": sequence,
        "location_group_id": group,
    }


def trip(number, trip_id):
    return {"_row_number": number, "trip_id": trip_id, "route_id": "R1", "service_id": "SV"}


STOPS = [
    stop(2, "S1", "Stop One"),
    stop(3, "S2", "Stop Two"),
    stop(4, "ST1", "Station", STATION),
    stop(5, "S3", "Stop Three"),
    stop(6, "E1", "Entrance", ENTRANCE, "ST1"),
    stop(7, "S4", "Stop Four"),
]
TRIPS = [trip(number, f"T{number - 1}") for number in range(2, 8)]
STOP_TIMES = [
    stop_time(2, "T1", "S1", 1),
    stop_time(3, "T1", "S4", 2),
    stop_time(4, "T3", "S1", 5),
    stop_time(5, "T3", "S4", 2),
    stop_time(6, "T4", "S1", 1),
    stop_time(7, "T5", "S1", 1),
    stop_time(8, "T4", "S4", 2),
    stop_time(9, "T5", "S4", 2),
    stop_time(10, "T1", "ST1", 3),
    stop_time(11, "T6", None, 1, group="G1"),
    stop_time(12, "T6", "S4", 2),
]
TABLES = {
    "stops.txt": STOPS,
    "trips.txt": TRIPS,
    "stop_times.txt": STOP_TIMES,
    "location_groups.txt": [
        {"_row_number": 2, "location_group_id": "G1", "location_group_name": "Group One"}
    ],
    "location_group_stops.txt": [{"_row_number": 2, "location_group_id": "G1", "stop_id": "S3"}],
}

MEASURED = {
    "unused_trip": [{"tripId": "T2", "csvRowNumber": 3}],
    "unsorted_stop_times": [
        {"tripId": "T1", "startCsvRowNumber": 2, "endCsvRowNumber": 10},
        {"tripId": "T3", "startCsvRowNumber": 4, "endCsvRowNumber": 5},
        {"tripId": "T4", "startCsvRowNumber": 6, "endCsvRowNumber": 8},
        {"tripId": "T5", "startCsvRowNumber": 7, "endCsvRowNumber": 9},
    ],
    "stop_without_stop_time": [{"csvRowNumber": 3, "stopId": "S2", "stopName": "Stop Two"}],
    "location_with_unexpected_stop_time": [
        {"csvRowNumber": 4, "stopId": "ST1", "stopName": "Station", "stopTimeCsvRowNumber": 10}
    ],
}


def fire(code, tables=None):
    registry.load_rules()
    feed = FakeFeed(TABLES if tables is None else tables)
    return [n.context for n in registry.FILE_REGISTRY[code].func(feed, CTX)]


def stop_row(number, stop_id, location_type, parent=None):
    return {
        "_row_number": number,
        "stop_id": stop_id,
        "stop_name": stop_id,
        "location_type": location_type,
        "parent_station": parent,
    }
