"""TripAndShapeDistanceValidator: a trip claiming more distance than its shape has.

Measured on `tripshape`, which carries one trip per branch: an overrun whose last stop is far from
the shape's end, one whose last stop is nearly on it, a shape whose greatest distance is zero, a
trip that does not overrun, and a trip with no shape at all.

This validator uses the `S2LatLng` haversine overload, unlike the transfer pair next door which
uses the `S2Point` one. Confirmed by value: the haversine reproduces the jar's
111.19510117719409 exactly and the vector form gives 111.19510117700135.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")
EXCEEDS = "trip_distance_exceeds_shape_distance"
BELOW = "trip_distance_exceeds_shape_distance_below_threshold"

STOPS = [
    {"_row_number": 2, "stop_id": "A", "stop_lat": 40.0, "stop_lon": -73.0},
    {"_row_number": 3, "stop_id": "B", "stop_lat": 40.001, "stop_lon": -73.0},
    {"_row_number": 4, "stop_id": "NEAR", "stop_lat": 40.00005, "stop_lon": -73.0},
]


def shape_point(row, shape_id, sequence, distance):
    return {
        "_row_number": row,
        "shape_id": shape_id,
        "shape_pt_sequence": sequence,
        "shape_dist_traveled": distance,
        "shape_pt_lat": 40.0,
        "shape_pt_lon": -73.0,
    }


def stop_time(row, trip_id, stop_id, sequence, distance):
    return {
        "_row_number": row,
        "trip_id": trip_id,
        "stop_id": stop_id,
        "stop_sequence": sequence,
        "shape_dist_traveled": distance,
    }


def trip(row, trip_id, shape_id):
    return {"_row_number": row, "trip_id": trip_id, "shape_id": shape_id}


def tables(trips, times, shapes, stops=None):
    return {
        "trips.txt": trips,
        "stop_times.txt": times,
        "shapes.txt": shapes,
        "stops.txt": STOPS if stops is None else stops,
    }


def fire(code, feed_tables, unindexable=frozenset()):
    registry.load_rules()
    feed = FakeFeed(feed_tables, unindexable=unindexable)
    return [notice.context for notice in registry.FILE_REGISTRY[code].func(feed, CTX)]


def overrun(last_stop="B", shape_max=100.0, trip_max=200.0, shape_id="SH1"):
    return tables(
        [trip(2, "T", shape_id)],
        [stop_time(2, "T", "A", 1, 0.0), stop_time(3, "T", last_stop, 2, trip_max)],
        [shape_point(2, shape_id, 1, 0.0), shape_point(3, shape_id, 2, shape_max)],
    )


def test_an_overrun_far_from_the_shape_end_is_an_error():
    """Measured: the last stop is 111.19510117719409 m from the shape's furthest point, over the
    11.1 m threshold."""
    assert fire(EXCEEDS, overrun()) == [
        {
            "tripId": "T",
            "shapeId": "SH1",
            "maxTripDistanceTraveled": 200.0,
            "maxShapeDistanceTraveled": 100.0,
            "geoDistanceToShape": 111.19510117719409,
        }
    ]
    assert fire(BELOW, overrun()) == []


def test_an_overrun_near_the_shape_end_is_only_a_warning():
    """Measured: 5.5597550589304365 m, under the threshold. The distance decides which code
    fires, not the size of the overrun, which is 100 either way."""
    assert fire(BELOW, overrun(last_stop="NEAR")) == [
        {
            "tripId": "T",
            "shapeId": "SH1",
            "maxTripDistanceTraveled": 200.0,
            "maxShapeDistanceTraveled": 100.0,
            "geoDistanceToShape": 5.5597550589304365,
        }
    ]
    assert fire(EXCEEDS, overrun(last_stop="NEAR")) == []


@pytest.mark.parametrize("code", [EXCEEDS, BELOW])
def test_a_shape_whose_greatest_distance_is_zero_is_skipped(code):
    """`if (maxShapeDist == 0) return`, which also covers a shape whose points leave
    shape_dist_traveled unset: the getter reads 0 and the guard catches it."""
    assert fire(code, overrun(shape_max=0.0)) == []


@pytest.mark.parametrize("code", [EXCEEDS, BELOW])
def test_a_trip_within_its_shape_draws_nothing(code):
    """The negative fixture: the comparison is `>`, so equal distances are fine too."""
    assert fire(code, overrun(trip_max=50.0)) == []
    assert fire(code, overrun(trip_max=100.0)) == []


@pytest.mark.parametrize("code", [EXCEEDS, BELOW])
def test_a_trip_with_no_shape_is_skipped(code):
    """An unset shape_id reads as "" through the getter, and `byShapeId("")` finds no shape, so
    the trip is skipped at the empty lookup rather than by a presence test. Same outcome here,
    but the reason matters: a shape whose id really is "" would be found."""
    assert fire(code, overrun(shape_id=None)) == []


@pytest.mark.parametrize("code", [EXCEEDS, BELOW])
def test_a_trip_with_no_stop_times_is_skipped(code):
    """`nbStopTimes == 0` returns before any distance is read."""
    assert fire(code, tables([trip(2, "T", "SH1")], [], [shape_point(2, "SH1", 1, 100.0)])) == []


@pytest.mark.parametrize("code", [EXCEEDS, BELOW])
def test_a_last_stop_that_does_not_exist_is_skipped(code):
    """The stop lookup returning empty ends the check, so a broken reference is left to
    foreign_key_violation rather than measured from the origin. That is the opposite of
    TransferDistanceValidator, which measures an unresolvable stop from latitude 0."""
    feed = overrun()
    feed["stop_times.txt"][1]["stop_id"] = "NOSUCH"
    assert fire(code, feed) == []


def test_a_tie_keeps_the_first_point_in_sequence_order_not_file_order():
    """`byShapeId` hands the validator a list sorted by shape_pt_sequence, and `Stream.max` keeps
    the first tie *of that list*.

    The distinction only shows when file order and sequence order disagree, which the previous
    version of this test did not arrange: it laid the rows out in sequence order and so passed
    against either reading. A review built the feed that separates them, and the jar picked the
    sequence-1 point where file order picked sequence 2 and landed the notice in the other band.
    """
    feed = overrun()
    feed["shapes.txt"] = [
        {**shape_point(2, "SH1", 2, 100.0), "shape_pt_lat": 41.0},
        shape_point(3, "SH1", 1, 100.0),
    ]
    # The sequence-1 point sits at latitude 40.0, so the last stop is 111 m from it: the error
    # band. Reading file order would measure from latitude 41.0 instead, 111 km away, which is
    # the same band here and a different distance, so the value is what this test turns on.
    assert [row["geoDistanceToShape"] for row in fire(EXCEEDS, feed)] == [111.19510117719409]
    assert fire(BELOW, feed) == []


def test_equal_stop_sequences_keep_the_last_row():
    """The container sorts stop times stably and the validator takes `get(size - 1)`, so among
    rows sharing the greatest stop_sequence the last in file order wins.

    Measured by a review on two rows at sequence 1: the far stop first, the near one second. The
    jar reports the near one, which is the below-threshold band.
    """
    feed = overrun()
    feed["stop_times.txt"] = [
        stop_time(2, "T", "B", 1, 200.0),
        stop_time(3, "T", "NEAR", 1, 200.0),
    ]
    assert [row["geoDistanceToShape"] for row in fire(BELOW, feed)] == [5.5597550589304365]
    assert fire(EXCEEDS, feed) == []


@pytest.mark.parametrize("code", [EXCEEDS, BELOW])
@pytest.mark.parametrize("failed", ["trips.txt", "stop_times.txt", "shapes.txt", "stops.txt"])
def test_any_failed_table_silences_both_codes(code, failed):
    """All four containers are injected, so a failure in any of them stops the validator."""
    from gtfs_validator.rules.runner import DependencyFailed

    with pytest.raises(DependencyFailed):
        fire(code, overrun(), frozenset({failed}))
