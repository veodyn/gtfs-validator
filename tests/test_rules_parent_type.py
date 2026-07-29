"""ParentStationValidator: a location whose parent is the wrong kind of place.

Measured on `parenttype`, which carries one correct and one wrong parent for each location type
that has an expected parent, plus a location whose parent does not exist and one whose own
location_type is not a value the enum defines.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")
CODE = "wrong_parent_location_type"

STOP, STATION, ENTRANCE, NODE, BOARDING_AREA = 0, 1, 2, 3, 4


def stop(row, stop_id, name, location_type, parent=None):
    return {
        "_row_number": row,
        "stop_id": stop_id,
        "stop_name": name,
        "location_type": location_type,
        "parent_station": parent,
    }


STOPS = [
    stop(2, "ST", "A Station", STATION),
    stop(3, "PLAT", "A Platform", STOP, "ST"),
    stop(4, "BADPLAT", "Bad Platform", STOP, "PLAT"),
    stop(5, "ENT", "An Entrance", ENTRANCE, "PLAT"),
    stop(6, "NODE", "A Node", NODE, "ENT"),
    stop(7, "BA", "A Boarding Area", BOARDING_AREA, "PLAT"),
    stop(8, "BADBA", "Bad Boarding Area", BOARDING_AREA, "ST"),
    stop(9, "ORPHAN", "Orphan", STOP, "NOSUCH"),
    stop(10, "WEIRD", "Weird Type", 7, "ST"),
]


def fire(rows=None, unindexable=frozenset()):
    registry.load_rules()
    feed = FakeFeed({"stops.txt": STOPS if rows is None else rows}, unindexable=unindexable)
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(feed, CTX)]


def test_every_wrong_parent_is_reported_in_file_order():
    """Measured on the jar: four notices, and the location types are reported as integers
    rather than enum names, which is the opposite of the stop-access pair on stops.txt."""
    assert fire() == [
        {
            "csvRowNumber": 4, "stopId": "BADPLAT", "stopName": "Bad Platform",
            "locationType": 0, "parentCsvRowNumber": 3, "parentStation": "PLAT",
            "parentStopName": "A Platform", "parentLocationType": 0, "expectedLocationType": 1,
        },
        {
            "csvRowNumber": 5, "stopId": "ENT", "stopName": "An Entrance",
            "locationType": 2, "parentCsvRowNumber": 3, "parentStation": "PLAT",
            "parentStopName": "A Platform", "parentLocationType": 0, "expectedLocationType": 1,
        },
        {
            "csvRowNumber": 6, "stopId": "NODE", "stopName": "A Node",
            "locationType": 3, "parentCsvRowNumber": 5, "parentStation": "ENT",
            "parentStopName": "An Entrance", "parentLocationType": 2, "expectedLocationType": 1,
        },
        {
            "csvRowNumber": 8, "stopId": "BADBA", "stopName": "Bad Boarding Area",
            "locationType": 4, "parentCsvRowNumber": 2, "parentStation": "ST",
            "parentStopName": "A Station", "parentLocationType": 1, "expectedLocationType": 0,
        },
    ]


def test_a_boarding_area_expects_a_platform_not_a_station():
    """The one location type whose expected parent is not a station: a boarding area belongs to
    a platform. BA under PLAT is silent and BADBA under ST is not, which is the pair that shows
    the table is not "everything wants a station"."""
    reported = {row["stopId"] for row in fire()}
    assert "BA" not in reported
    assert "BADBA" in reported


def test_a_station_is_skipped_by_this_rule():
    """A station with a parent is `station_with_parent_station`'s business, and this rule
    `continue`s before looking. Measured: giving ST a parent adds nothing here."""
    rows = [stop(2, "ST", "A Station", STATION, "OTHER"), stop(3, "OTHER", "Other", STATION)]
    assert fire(rows) == []


def test_a_missing_parent_is_left_to_the_foreign_key_rule():
    """ORPHAN names a parent that does not exist, and upstream `continue`s on the empty lookup
    rather than reporting a wrong type. Reporting one here would double-report a broken
    reference that foreign_key_violation already covers."""
    assert "ORPHAN" not in {row["stopId"] for row in fire()}


def test_an_unrecognised_location_type_has_no_expectation():
    """`expectedParentLocationType` returns UNRECOGNIZED for anything outside the enum, and the
    guard skips it. WEIRD has location_type 7 under a station and draws nothing."""
    assert "WEIRD" not in {row["stopId"] for row in fire()}


def test_a_location_with_no_parent_is_silent():
    """The negative fixture: `hasParentStation()` gates the loop."""
    assert fire([stop(2, "SOLO", "Solo", STOP)]) == []


def test_a_failed_stops_table_silences_the_rule():
    from gtfs_validator.rules.runner import DependencyFailed

    with pytest.raises(DependencyFailed):
        fire(unindexable=frozenset({"stops.txt"}))


def test_an_unset_stop_name_is_reported_as_an_empty_string():
    """Measured on `stopfeed`, whose stops carry no stop_name: the jar sends `"stopName": ""`.

    An unset String field reads as "" through its entity getter, so Gson writes an empty string
    where passing None drops the key from our report. Ten other rules on stops.txt already spelled
    this `or ""`; this rule was written without it and the sweep caught it on the next run. The
    convention was there to follow.
    """
    rows = [
        stop(2, "ST", None, STATION),
        stop(3, "BA", None, BOARDING_AREA, "ST"),
    ]
    assert fire(rows) == [
        {
            "csvRowNumber": 3, "stopId": "BA", "stopName": "",
            "locationType": 4, "parentCsvRowNumber": 2, "parentStation": "ST",
            "parentStopName": "", "parentLocationType": 1, "expectedLocationType": 0,
        }
    ]
