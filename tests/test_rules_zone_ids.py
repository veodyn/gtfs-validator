"""StopZoneIdValidator: a stop with no zone_id on a route whose fares use zones.

Measured on `zoneids`: five stops, of which only the one served by a route named in a zone-using
fare rule is reported.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")
CODE = "stop_without_zone_id"

STOPS = [
    {"_row_number": 2, "stop_id": "Z1", "stop_name": "Has Zone", "location_type": 0,
     "zone_id": "ZA"},
    {"_row_number": 3, "stop_id": "N1", "stop_name": "No Zone", "location_type": 0,
     "zone_id": None},
    {"_row_number": 4, "stop_id": "N2", "stop_name": "No Zone Other", "location_type": 0,
     "zone_id": None},
    {"_row_number": 5, "stop_id": "ST", "stop_name": "Station", "location_type": 1,
     "zone_id": None},
]
TRIPS = [
    {"_row_number": 2, "trip_id": "T1", "route_id": "R1"},
    {"_row_number": 3, "trip_id": "T2", "route_id": "R2"},
]
TIMES = [
    {"_row_number": 2, "trip_id": "T1", "stop_id": "Z1", "stop_sequence": 1},
    {"_row_number": 3, "trip_id": "T1", "stop_id": "N1", "stop_sequence": 2},
    {"_row_number": 4, "trip_id": "T2", "stop_id": "N2", "stop_sequence": 1},
    {"_row_number": 5, "trip_id": "T2", "stop_id": "ST", "stop_sequence": 2},
]
ZONED_RULES = [
    {"_row_number": 2, "fare_id": "F1", "route_id": "R1", "origin_id": "ZA",
     "destination_id": None, "contains_id": None},
    {"_row_number": 3, "fare_id": "F1", "route_id": "R2", "origin_id": None,
     "destination_id": None, "contains_id": None},
]


def fire(rules=None, stops=None):
    registry.load_rules()
    feed = FakeFeed({
        "stops.txt": STOPS if stops is None else stops,
        "trips.txt": TRIPS,
        "stop_times.txt": TIMES,
        "fare_rules.txt": ZONED_RULES if rules is None else rules,
    })
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(feed, CTX)]


def test_only_a_stop_on_a_zoned_route_is_reported():
    """Measured: N1 is on R1, whose fare rule names an origin zone. N2 is on R2, whose rule names
    none, so two stops equally lacking a zone_id are treated differently."""
    assert fire() == [{"stopId": "N1", "stopName": "No Zone", "csvRowNumber": 3}]


def test_a_feed_whose_fare_rules_use_no_zones_reports_nothing():
    """The whole check is gated on some rule setting origin, destination or contains. Without
    that, no stop is reported however many lack a zone_id."""
    flat = [{"_row_number": 2, "fare_id": "F1", "route_id": "R1", "origin_id": None,
             "destination_id": None, "contains_id": None}]
    assert fire(rules=flat) == []


def test_an_absent_fare_rules_table_reports_nothing():
    assert fire(rules=[]) == []


@pytest.mark.parametrize("field", ["origin_id", "destination_id", "contains_id"])
def test_any_of_the_three_zone_fields_opens_the_gate(field):
    rules = [{"_row_number": 2, "fare_id": "F1", "route_id": "R1", "origin_id": None,
              "destination_id": None, "contains_id": None, field: "ZA"}]
    assert [row["stopId"] for row in fire(rules=rules)] == ["N1"]


def test_a_station_and_a_stop_with_a_zone_are_skipped():
    """A station has no fare zone of its own, and a stop that declares one is not missing it."""
    reported = {row["stopId"] for row in fire()}
    assert "ST" not in reported
    assert "Z1" not in reported


def test_a_stop_no_trip_serves_is_not_reported():
    """Upstream reaches this through an empty route set rather than a special case."""
    stops = [*STOPS, {"_row_number": 6, "stop_id": "UN", "stop_name": "Unserved",
                      "location_type": 0, "zone_id": None}]
    assert "UN" not in {row["stopId"] for row in fire(stops=stops)}
