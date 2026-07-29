"""fast_travel_between_far_stops, measured on the same `fast1` probe.

Two stops are "far" when more than 10 km of consecutive hops separate them, and the scan that
finds them is not the neighbour walk next door. For each stop time with an arrival, upstream
walks *backwards* accumulating distance, and reports the first pair that is both over the
speed threshold and over 10 km apart. It then stops looking at the trip entirely.

Three consequences, one test each: a trip of eleven slow hops draws a notice the consecutive
code cannot see; a trip draws at most one notice however many far pairs it has; and a stop id
that resolves to no row aborts the whole trip rather than skipping its own pair.
"""

from __future__ import annotations

import pytest

from fasttravel import (
    FAR,
    FAR_KM,
    ORIGIN_KM,
    RAIL,
    T0800,
    chain,
    fire,
    route,
    stop,
    stop_time,
    stops,
    trip,
)
from gtfs_validator.notices import Severity
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import DependencyFailed


def far(stop_times, **kwargs):
    return fire(FAR, stop_times, **kwargs)


def test_a_far_pair_names_every_field_the_jar_does():
    """fast1 TB, rows 4 and 5: 11.12 km in ten seconds, which is over both thresholds.

    The context is the consecutive code's, field for field. The two notices are different
    codes on the same pair, and this is the feed where that happens.
    """
    rows = [
        stop_time(4, "TB", 1, "A", T0800),
        stop_time(5, "TB", 2, "C", T0800 + 10),
    ]
    assert far(rows, trips=[trip("TB", 3)]) == [
        {
            "tripCsvRowNumber": 3,
            "tripId": "TB",
            "routeId": "R1",
            "speedKph": 4003.0236423894266,
            "distanceKm": FAR_KM,
            "csvRowNumber1": 4,
            "stopSequence1": 1,
            "stopId1": "A",
            "stopName1": "Stop A",
            "departureTime1": "08:00:00",
            "csvRowNumber2": 5,
            "stopSequence2": 2,
            "stopId2": "C",
            "stopName2": "Stop C",
            "arrivalTime2": "08:00:10",
        }
    ]


def test_a_pair_under_ten_kilometres_apart_is_not_far():
    """fast1 TA, rows 2 and 3: 5.56 km in ten seconds.

    2001 km/h on a bus, and silent here. Speed alone is the consecutive code's business; this
    one needs the distance as well.
    """
    rows = [
        stop_time(2, "TA", 1, "A", T0800),
        stop_time(3, "TA", 2, "B", T0800 + 10),
    ]
    assert far(rows, trips=[trip("TA", 2)]) == []


def test_distance_accumulates_over_hops_that_are_each_slow_enough():
    """fast1 TI, rows 22 to 32: eleven stops 1.22 km apart, every one timed 08:00:00.

    No consecutive hop is fast: with equal times the elapsed second count is clamped to a
    minute, which makes each hop 73 km/h against a bus's 150. The span is another matter, and
    the jar reports P0 to P9 at 660.4989009942303 km/h over 11.008315016570505 km.

    P9 and not P10, which is the early exit made visible: the backward walk from P9 is the
    first to accumulate over 10 km, and upstream returns from the trip once it reports.
    """
    stop_rows, rows = chain()
    notices = far(rows, trips=[trip("TI", 11)], stop_rows=stop_rows)
    assert [
        (row["csvRowNumber1"], row["stopId1"], row["csvRowNumber2"], row["stopId2"])
        for row in notices
    ] == [(22, "P0", 31, "P9")]
    assert [(row["distanceKm"], row["speedKph"]) for row in notices] == [
        (11.008315016570505, 660.4989009942303)
    ]


def test_a_stop_that_does_not_exist_aborts_the_whole_trip():
    """fast1 TL, rows 39 to 41, whose middle row names a stop id nothing declares.

    Nothing, although rows 39 and 41 are 11.12 km apart in ten seconds and the consecutive
    code reports exactly that pair. The backward walk reaches the unknown stop first, as the
    *end* of a pair, and upstream returns from the trip rather than skipping the row.
    """
    rows = [
        stop_time(39, "TL", 1, "A", T0800),
        stop_time(40, "TL", 2, "Z", T0800 + 5),
        stop_time(41, "TL", 3, "C", T0800 + 10),
    ]
    assert far(rows, trips=[trip("TL", 15)]) == []


def test_identical_trips_are_each_reported_from_their_own_rows():
    """fast1 TK1 and TK2, rows 35 to 38, identical trips 11.12 km apart in ten seconds.

    Two notices naming rows 37, 38 and 35, 36: each trip's own. The consecutive code gives
    both notices the group's first trip's rows, and this one does not. Reading either loop and
    assuming the other matches puts the wrong row numbers in half the notices.
    """
    rows = [
        stop_time(35, "TK1", 1, "A", T0800),
        stop_time(36, "TK1", 2, "C", T0800 + 10),
        stop_time(37, "TK2", 1, "A", T0800),
        stop_time(38, "TK2", 2, "C", T0800 + 10),
    ]
    trips = [trip("TK1", 13, route_id="R5"), trip("TK2", 14, route_id="R5")]
    notices = far(rows, trips=trips, routes=[route("R5", 6)])
    assert [(row["tripId"], row["csvRowNumber1"], row["csvRowNumber2"]) for row in notices] == [
        ("TK2", 37, 38),
        ("TK1", 35, 36),
    ]


def test_the_threshold_comes_from_the_route_type_here_too():
    """fast1 TC, rows 6 and 7: 11.12 km in two minutes, over 10 km but only 222.39 km/h.

    Silent on rail and reported on a bus, from the same rows: the distance qualifies either
    way, so this isolates the speed half of the test.
    """
    rows = [
        stop_time(6, "TC", 1, "A", T0800),
        stop_time(7, "TC", 2, "C", T0800 + 120),
    ]
    trips = [trip("TC", 2, route_id="R2")]
    assert far(rows, trips=trips, routes=[route("R2", 2, route_type=RAIL)]) == []
    assert [row["speedKph"] for row in far(rows, trips=trips, routes=[route("R2", 2)])] == [
        222.39020235496815
    ]


def test_a_stop_at_the_origin_is_measured_here_too():
    """fast1 TN, rows 44 and 45. The origin is a position, so the pair is 8652 km apart."""
    rows = [
        stop_time(44, "TN", 1, "A", T0800),
        stop_time(45, "TN", 2, "NULL", T0800 + 10),
    ]
    extra = (stop("NULL", 5, 0.0, longitude=0.0),)
    notices = far(rows, trips=[trip("TN", 17)], stop_rows=stops("A", extra=extra))
    assert [row["distanceKm"] for row in notices] == [ORIGIN_KM]


def test_a_trip_whose_route_is_missing_is_skipped():
    """fast1 TM, rows 42 and 43. The group is dropped before either code runs."""
    rows = [
        stop_time(42, "TM", 1, "A", T0800),
        stop_time(43, "TM", 2, "C", T0800 + 10),
    ]
    assert far(rows, trips=[trip("TM", 16, route_id="R9")]) == []


def test_the_code_is_registered_as_a_warning():
    registry.load_rules()
    assert registry.FILE_REGISTRY[FAR].severity is Severity.WARNING


@pytest.mark.parametrize("table", ["stop_times.txt", "trips.txt", "routes.txt", "stops.txt"])
def test_any_of_the_four_tables_failing_silences_the_rule(table):
    """The same four containers as the consecutive code, since it is one validator upstream."""
    rows = [
        stop_time(4, "TB", 1, "A", T0800),
        stop_time(5, "TB", 2, "C", T0800 + 10),
    ]
    with pytest.raises(DependencyFailed):
        far(rows, trips=[trip("TB", 3)], unindexable=frozenset({table}))
