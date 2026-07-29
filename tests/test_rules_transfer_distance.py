"""TransferDistanceValidator: a transfer between two stops implausibly far apart.

Measured on `xferdist`, whose coordinates were chosen so every reported distance matches the jar's
last digit exactly. That is not automatic: the `S2Point` overload upstream uses here differs from
ours in the last digit on 52.9% of transfer-sized pairs (divergence 12), so a probe meant to test
branch logic has to sit on pairs where the two agree.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import DependencyFailed

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")

ABOVE = "transfer_distance_above_2_km"
TOO_LARGE = "transfer_distance_too_large"


def stop(row, stop_id, lat=None, lon=None, location_type=0, parent=None):
    return {
        "_row_number": row,
        "stop_id": stop_id,
        "stop_name": stop_id,
        "stop_lat": lat,
        "stop_lon": lon,
        "location_type": location_type,
        "parent_station": parent,
    }


def transfer(row, from_stop, to_stop):
    return {
        "_row_number": row,
        "from_stop_id": from_stop,
        "to_stop_id": to_stop,
        "transfer_type": 0,
    }


STOPS = [
    stop(2, "A", 40.0, -73.0),
    stop(3, "B", 40.026, -73.0),
    stop(4, "C", 40.094, -73.0),
    stop(5, "GP", 40.094, -73.0, location_type=1),
    stop(6, "P", location_type=1, parent="GP"),
    stop(7, "CHILD", parent="P"),
    stop(8, "DIRECT", parent="GP"),
]


def fire(code, tables=None, unindexable=frozenset()):
    registry.load_rules()
    base = {"stops.txt": STOPS, "transfers.txt": []}
    feed = FakeFeed(base if tables is None else tables, unindexable=unindexable)
    return [notice.context for notice in registry.FILE_REGISTRY[code].func(feed, CTX)]


def with_transfers(rows):
    return {"stops.txt": STOPS, "transfers.txt": rows}


def test_a_transfer_over_two_kilometres_is_a_warning():
    """Measured: A to B is 2891.072630614795 m, reported as km."""
    got = fire(ABOVE, with_transfers([transfer(2, "A", "B")]))
    assert got == [
        {
            "csvRowNumber": 2,
            "fromStopId": "A",
            "toStopId": "B",
            "distanceKm": 2.891072630614795,
        }
    ]


def test_a_transfer_over_ten_kilometres_is_the_other_code():
    """Measured: A to C is 10452.33951068394 m. The thresholds are on metres and the notice
    carries kilometres, so the two units sit one line apart in the validator."""
    got = fire(TOO_LARGE, with_transfers([transfer(2, "A", "C")]))
    assert got == [
        {
            "csvRowNumber": 2,
            "fromStopId": "A",
            "toStopId": "C",
            "distanceKm": 10.45233951068394,
        }
    ]
    assert fire(ABOVE, with_transfers([transfer(2, "A", "C")])) == []


def test_a_transfer_between_one_stop_and_itself_is_zero():
    """A stop paired with itself measures 0 m and draws nothing."""
    assert fire(ABOVE, with_transfers([transfer(2, "A", "A")])) == []
    assert fire(TOO_LARGE, with_transfers([transfer(2, "A", "A")])) == []


@pytest.mark.parametrize(
    ("longitude", "distance", "expected"),
    [
        (0.01798640388669373, 1999.9999999999995, None),
        (0.017986403886693734, 2000.0000000000002, ABOVE),
        (0.08993201943346865, 9999.999999999998, ABOVE),
        (0.08993201943346867, 10000.0, ABOVE),
        (0.0899320194334687, 10000.000000000004, TOO_LARGE),
    ],
)
def test_the_bands_meet_exactly_at_their_thresholds(longitude, distance, expected):
    """Both boundaries, at coordinates that land on them to the last bit.

    This replaces a test that claimed to check an exact 2,000 m transfer while using a stop paired
    with itself, which is 0 m: it would have passed against almost any band logic. A review built
    the feed that finds the real boundaries, and every value here was measured on the jar first.

    The interesting one is exactly 10,000 m, which draws the *lower* code. Upstream tests
    `> 10_000` first and falls through to `> 2_000`, so both bounds are strict and 10,000 belongs
    to the band below. Written as `>=` on the upper bound, this row would have been the other code.
    """
    tables = with_transfers([transfer(2, "ORIGIN", "TARGET")])
    tables["stops.txt"] = [
        stop(2, "ORIGIN", 0.0, 0.0),
        stop(3, "TARGET", 0.0, longitude),
    ]
    from gtfs_validator.s2earth import point_distance_meters

    assert point_distance_meters(0.0, 0.0, 0.0, longitude) == distance
    for code in (ABOVE, TOO_LARGE):
        got = fire(code, tables)
        assert (got != []) == (code == expected), f"{code} at {distance}"


def test_a_stop_without_coordinates_borrows_its_parents():
    """Measured: DIRECT has no coordinates and its parent GP sits at C's position, so the
    distance is C's. `StopUtil.getStopOrParentLatLng` walks up rather than skipping the row."""
    got = fire(TOO_LARGE, with_transfers([transfer(2, "DIRECT", "A")]))
    assert [row["distanceKm"] for row in got] == [10.45233951068394]


def test_the_walk_reaches_a_grandparent():
    """CHILD has no coordinates, nor does its parent P, and P's parent GP does. Measured: the
    same distance as the direct child, so the loop runs more than one hop.

    Upstream caps it at three iterations to survive a parent cycle, which is why this is a walk
    with a bound rather than a recursion.
    """
    got = fire(TOO_LARGE, with_transfers([transfer(2, "CHILD", "A")]))
    assert [row["distanceKm"] for row in got] == [10.45233951068394]


def test_an_unresolvable_stop_is_measured_from_the_origin():
    """Measured: a transfer to a stop that does not exist reports 8568.438594310714 km.

    `getStopOrParentLatLng` returns `S2LatLng.CENTER`, which is latitude 0, longitude 0. So the
    notice is real and its distance is measured from a point in the Gulf of Guinea. Skipping the
    row instead would drop a notice the jar reports; treating the fallback as an error would
    report a different one.
    """
    got = fire(TOO_LARGE, with_transfers([transfer(2, "A", "NOSUCH")]))
    assert got == [
        {
            "csvRowNumber": 2,
            "fromStopId": "A",
            "toStopId": "NOSUCH",
            "distanceKm": 8568.438594310714,
        }
    ]


@pytest.mark.parametrize("code", [ABOVE, TOO_LARGE])
def test_a_transfer_missing_either_end_is_skipped(code):
    """`hasFromStopId() && hasToStopId()` gates the loop, so a blank end is not measured against
    the origin the way an unresolvable *named* stop is. The two cases look alike and are not."""
    assert fire(code, with_transfers([transfer(2, None, "B")])) == []
    assert fire(code, with_transfers([transfer(2, "A", None)])) == []


@pytest.mark.parametrize("code", [ABOVE, TOO_LARGE])
@pytest.mark.parametrize("failed", ["transfers.txt", "stops.txt"])
def test_either_failed_table_silences_both_codes(code, failed):
    """One validator takes both containers, so a failure in either stops both codes.

    Asserted as the raise rather than as an empty result, which is the opposite of the URL cohort
    next door, and the difference is not stylistic. These rules read both of their gating tables,
    so `rows()` raising is what silences them and the runner discards whatever they had produced.
    The URL codes are gated by a table two of them never read, so they need an explicit
    `dependency_failed` check and return normally.
    """
    with pytest.raises(DependencyFailed):
        fire(code, with_transfers([transfer(2, "A", "C")]), frozenset({failed}))


@pytest.mark.parametrize("code", [ABOVE, TOO_LARGE])
def test_a_nearby_transfer_draws_nothing(code):
    """The negative fixture: two stops a few hundred metres apart."""
    tables = with_transfers([transfer(2, "A", "NEAR")])
    tables["stops.txt"] = [*STOPS, stop(9, "NEAR", 40.001, -73.0)]
    assert fire(code, tables) == []
