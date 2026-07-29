"""TransfersTripReferenceValidator: a transfer whose trip contradicts its route or stop.

Measured on `xfertrip`, which carries a route mismatch, a matching route, a stop the trip never
calls at, a station whose platform one trip serves and another does not, an entrance, and ends
naming a trip and a stop that do not exist.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import DependencyFailed

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")
ROUTE_CODE = "transfer_with_invalid_trip_and_route"
STOP_CODE = "transfer_with_invalid_trip_and_stop"

STOPS = [
    {"_row_number": 2, "stop_id": "P1", "location_type": 0, "parent_station": "ST"},
    {"_row_number": 3, "stop_id": "P2", "location_type": 0, "parent_station": None},
    {"_row_number": 4, "stop_id": "ST", "location_type": 1, "parent_station": None},
    {"_row_number": 5, "stop_id": "ENT", "location_type": 2, "parent_station": "ST"},
    {"_row_number": 6, "stop_id": "LONE", "location_type": 0, "parent_station": None},
]
TRIPS = [
    {"_row_number": 2, "trip_id": "T1", "route_id": "R1"},
    {"_row_number": 3, "trip_id": "T2", "route_id": "R2"},
]
TIMES = [
    {"_row_number": 2, "trip_id": "T1", "stop_id": "P1", "stop_sequence": 1},
    {"_row_number": 3, "trip_id": "T1", "stop_id": "P2", "stop_sequence": 2},
    {"_row_number": 4, "trip_id": "T2", "stop_id": "P2", "stop_sequence": 1},
    {"_row_number": 5, "trip_id": "T2", "stop_id": "LONE", "stop_sequence": 2},
]


def transfer(row, **fields):
    base = {
        "_row_number": row,
        "from_stop_id": None, "to_stop_id": None,
        "from_trip_id": None, "to_trip_id": None,
        "from_route_id": None, "to_route_id": None,
        "transfer_type": 1,
    }
    base.update(fields)
    return base


def fire(code, transfers, unindexable=frozenset()):
    registry.load_rules()
    feed = FakeFeed(
        {"transfers.txt": transfers, "trips.txt": TRIPS, "stops.txt": STOPS,
         "stop_times.txt": TIMES},
        unindexable=unindexable,
    )
    return [notice.context for notice in registry.FILE_REGISTRY[code].func(feed, CTX)]


def test_a_route_that_the_trip_does_not_run_on_is_reported():
    """Measured: expectedRouteId is the trip's real route and routeId is the transfer's claim."""
    assert fire(ROUTE_CODE, [transfer(2, from_trip_id="T1", from_route_id="R2")]) == [
        {
            "csvRowNumber": 2, "tripFieldName": "from_trip_id", "tripId": "T1",
            "routeFieldName": "from_route_id", "routeId": "R2", "expectedRouteId": "R1",
        }
    ]


def test_a_matching_route_draws_nothing():
    assert fire(ROUTE_CODE, [transfer(2, from_trip_id="T1", from_route_id="R1")]) == []


def test_a_stop_the_trip_never_calls_at_is_reported():
    """T1 calls at P1 and P2, so naming LONE is a contradiction."""
    assert fire(STOP_CODE, [transfer(2, from_trip_id="T1", from_stop_id="LONE")]) == [
        {
            "csvRowNumber": 2, "tripFieldName": "from_trip_id", "tripId": "T1",
            "stopFieldName": "from_stop_id", "stopId": "LONE",
        }
    ]


def test_a_station_stands_for_its_platforms():
    """`expandStationIfNeeded`: a station is satisfied by a trip calling at any child platform.

    Measured both ways on the same station: T1 calls at its platform P1 and draws nothing, T2
    does not and draws the notice.
    """
    assert fire(STOP_CODE, [transfer(2, from_trip_id="T1", from_stop_id="ST")]) == []
    assert [row["stopId"] for row in
            fire(STOP_CODE, [transfer(2, from_trip_id="T2", from_stop_id="ST")])] == ["ST"]


def test_an_entrance_can_never_be_served():
    """Anything that is neither a platform nor a station expands to the *empty set*, so the
    notice always fires. Measured on an entrance under a station whose platform the trip does
    call at: the expansion is empty, not the station's children."""
    assert [row["stopId"] for row in
            fire(STOP_CODE, [transfer(2, from_trip_id="T1", from_stop_id="ENT")])] == ["ENT"]


@pytest.mark.parametrize("code", [ROUTE_CODE, STOP_CODE])
def test_a_missing_trip_or_stop_is_left_to_the_foreign_key_rules(code):
    """Upstream returns on either empty lookup, naming the foreign key validators that own it."""
    assert fire(code, [transfer(2, from_trip_id="NOSUCH", from_route_id="R2",
                                from_stop_id="LONE")]) == []
    assert fire(code, [transfer(2, from_trip_id="T1", from_stop_id="NOSUCH")]) == []


def test_both_ends_are_checked_independently():
    """Each direction is its own pass, so one transfer can draw two notices, and the route and
    stop questions do not gate each other."""
    rows = [transfer(2, from_trip_id="T1", from_stop_id="LONE",
                     to_trip_id="T2", to_stop_id="P1")]
    assert [row["tripFieldName"] for row in fire(STOP_CODE, rows)] == [
        "from_trip_id", "to_trip_id"
    ]


@pytest.mark.parametrize("code", [ROUTE_CODE, STOP_CODE])
@pytest.mark.parametrize("failed", ["transfers.txt", "trips.txt"])
def test_a_failed_table_silences_both_codes(code, failed):
    with pytest.raises(DependencyFailed):
        fire(code, [transfer(2, from_trip_id="T1", from_route_id="R2")], frozenset({failed}))
