"""DuplicateRouteNameValidator: two routes a passenger could not tell apart.

Measured on `routenames`, which carries an identical pair, a pair differing only in type, a pair
differing only in agency, a pair with no short name and a pair with no long name.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import DependencyFailed

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")
CODE = "duplicate_route_name"


def route(row, route_id, short="1", long="Main Line", route_type=3, agency="A1"):
    return {
        "_row_number": row, "route_id": route_id, "route_short_name": short,
        "route_long_name": long, "route_type": route_type, "agency_id": agency,
    }


def fire(rows, unindexable=frozenset()):
    registry.load_rules()
    feed = FakeFeed({"routes.txt": rows}, unindexable=unindexable)
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(feed, CTX)]


def test_an_identical_pair_is_reported_with_both_rows():
    assert fire([route(2, "R1"), route(3, "R2")]) == [
        {
            "csvRowNumber1": 2, "routeId1": "R1", "csvRowNumber2": 3, "routeId2": "R2",
            "routeShortName": "1", "routeLongName": "Main Line", "routeTypeValue": 3,
            "agencyId": "A1",
        }
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [("route_type", 2), ("agency", "A2"), ("short", "2"), ("long", "Other Line")],
)
def test_any_differing_key_field_makes_them_distinct(field, value):
    """All four fields are part of the key, so changing any one of them ends the match."""
    kwargs = {"route_type" if field == "route_type" else field: value}
    assert fire([route(2, "R1"), route(3, "R2", **kwargs)]) == []


def test_an_unset_name_is_the_empty_string_and_still_a_key():
    """Measured: two routes with no short name and the same long name are duplicates, and the
    notice reports routeShortName as "" rather than omitting it."""
    got = fire([route(2, "R1", short=None), route(3, "R2", short=None)])
    assert [row["routeShortName"] for row in got] == [""]


def test_three_identical_routes_pair_with_the_first():
    """`putIfAbsent` keeps the first route holding a key, so the third is paired with the first
    rather than the second. Two notices, not one, and not a chain."""
    got = fire([route(2, "R1"), route(3, "R2"), route(4, "R3")])
    assert [(row["csvRowNumber1"], row["csvRowNumber2"]) for row in got] == [(2, 3), (2, 4)]


def test_a_lone_route_draws_nothing():
    assert fire([route(2, "R1")]) == []


def test_a_failed_routes_table_silences_the_rule():
    with pytest.raises(DependencyFailed):
        fire([route(2, "R1"), route(3, "R2")], frozenset({"routes.txt"}))
