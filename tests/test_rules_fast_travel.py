"""fast_travel_between_consecutive_stops, measured on the `fast1` probe.

Seventeen trips, whose interesting ones are named in each test. Four numbers in this file are
the jar's and not derivable: the two distances, and the speeds 166.7926517662155 and
333.585303532431 that pin the two adjustments upstream makes to the elapsed time.

The rest of the file is about which rows a notice names, and that is where upstream is
surprising. A notice is issued per trip in the group, but the *stop times* it names come from
the group's first trip, not from the trip the notice is about. `fast1`'s TK1 and TK2 are
identical trips, and both consecutive notices name TK2's rows while the far-stop notices name
each trip's own. Reproducing that meant transcribing the two loops separately rather than
sharing one.
"""

from __future__ import annotations

import pytest

from fasttravel import (
    CONSECUTIVE,
    FAR_KM,
    NEAR_KM,
    ORIGIN_KM,
    RAIL,
    T0800,
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


def consecutive(stop_times, **kwargs):
    return fire(CONSECUTIVE, stop_times, **kwargs)


def test_a_fast_pair_names_every_field_the_jar_does():
    """fast1 TA, rows 2 and 3: 5.56 km in ten seconds on a bus.

    The whole context, in Gson's field order, measured rather than assembled.
    """
    rows = [
        stop_time(2, "TA", 1, "A", T0800),
        stop_time(3, "TA", 2, "B", T0800 + 10),
    ]
    assert consecutive(rows, trips=[trip("TA", 2)]) == [
        {
            "tripCsvRowNumber": 2,
            "tripId": "TA",
            "routeId": "R1",
            "speedKph": 2001.511821194586,
            "distanceKm": NEAR_KM,
            "csvRowNumber1": 2,
            "stopSequence1": 1,
            "stopId1": "A",
            "stopName1": "Stop A",
            "departureTime1": "08:00:00",
            "csvRowNumber2": 3,
            "stopSequence2": 2,
            "stopId2": "B",
            "stopName2": "Stop B",
            "arrivalTime2": "08:00:10",
        }
    ]


def test_the_threshold_comes_from_the_route_type():
    """fast1 TC, rows 6 and 7: 11.12 km in two minutes, which is 222.39 km/h.

    Silent on rail, whose threshold is 500, and reported on a bus, whose threshold is 150.
    The same rows both ways is what makes this about the route type and nothing else.
    """
    rows = [
        stop_time(6, "TC", 1, "A", T0800),
        stop_time(7, "TC", 2, "C", T0800 + 120),
    ]
    trips = [trip("TC", 2, route_id="R2")]
    assert consecutive(rows, trips=trips, routes=[route("R2", 2, route_type=RAIL)]) == []
    assert [row["speedKph"] for row in consecutive(rows, trips=trips, routes=[route("R2", 2)])] == [
        222.39020235496815
    ]


def test_an_unrecognised_route_type_falls_back_to_two_hundred():
    """fast1 TJ, rows 33 and 34, on a route whose type is 99.

    The value is outside the enum, so the row is kept with a warning and the getter returns
    the unrecognised constant, which upstream's switch does not name. 222.39 km/h is over the
    default 200 and under the 500 a reader might assume from `route_type` being unusable.
    """
    rows = [
        stop_time(33, "TJ", 1, "A", T0800),
        stop_time(34, "TJ", 2, "C", T0800 + 120),
    ]
    notices = consecutive(
        rows,
        trips=[trip("TJ", 12, route_id="R4")],
        routes=[route("R4", 5, route_type=99)],
    )
    assert [row["speedKph"] for row in notices] == [222.39020235496815]


def test_minute_resolution_times_get_a_minute_of_error_buffer():
    """fast1 TD, rows 8 and 9: 5.56 km between 08:00:00 and 08:01:00.

    166.7926517662155 km/h, which is 5.56 over 120 seconds rather than over 60. Upstream adds
    a minute when both times land on a minute, because a scheduling system that writes whole
    minutes leaves up to 30 seconds of error either side. Without the buffer this is
    333.585303532431 and still a notice, so only the reported speed shows the difference.
    """
    rows = [
        stop_time(8, "TD", 1, "A", T0800),
        stop_time(9, "TD", 2, "B", T0800 + 60),
    ]
    notices = consecutive(rows, trips=[trip("TD", 5)])
    assert [row["speedKph"] for row in notices] == [166.7926517662155]


def test_arriving_before_departing_is_clamped_to_one_minute():
    """fast1 TE, rows 10 and 11: departure 08:05:00, arrival 08:00:00.

    Time runs backwards, so upstream substitutes 60 seconds rather than dividing by a
    negative. 333.585303532431 km/h is 5.56 km over that minute, and it is the same number the
    buffer case would give without its buffer: two different adjustments, one arithmetic.
    """
    rows = [
        stop_time(10, "TE", 1, "A", T0800 + 300),
        stop_time(11, "TE", 2, "B", T0800),
    ]
    notices = consecutive(rows, trips=[trip("TE", 6)])
    assert [row["speedKph"] for row in notices] == [333.585303532431]


def test_an_unmeasurable_stop_does_not_advance_the_pair():
    """fast1 TG, rows 16 to 18, whose middle row names a location instead of a stop.

    The distance to it cannot be measured, so upstream skips the pair *without* moving its
    cursor, and the next comparison reaches back to row 16. The notice therefore spans the
    skipped row: 5.56 km from A to B in ten seconds, naming rows 16 and 18.
    """
    rows = [
        stop_time(16, "TG", 1, "A", T0800),
        stop_time(17, "TG", 2, None, T0800 + 5),
        stop_time(18, "TG", 3, "B", T0800 + 10),
    ]
    notices = consecutive(rows, trips=[trip("TG", 9)])
    assert [(row["csvRowNumber1"], row["csvRowNumber2"], row["distanceKm"]) for row in notices] == [
        (16, 18, NEAR_KM)
    ]


def test_a_missing_time_does_not_advance_the_pair_either():
    """fast1 TH, rows 19 to 21, whose middle row has no arrival time.

    The second `continue` is placed exactly like the first, so this too spans the row: rows
    19 and 21, 11.12 km, and not the 5.56 km hop the middle row would have made.
    """
    rows = [
        stop_time(19, "TH", 1, "A", T0800),
        stop_time(20, "TH", 2, "B", None, departure=T0800 + 5),
        stop_time(21, "TH", 3, "C", T0800 + 10),
    ]
    notices = consecutive(rows, trips=[trip("TH", 10)])
    assert [(row["csvRowNumber1"], row["csvRowNumber2"], row["distanceKm"]) for row in notices] == [
        (19, 21, FAR_KM)
    ]


def test_a_stop_that_does_not_exist_only_skips_its_own_pair():
    """fast1 TL, rows 39 to 41, whose middle row names a stop id nothing declares.

    One notice, rows 39 and 41. The far-stop code aborts the trip on the same row; this one
    does not, and the pair of tests either side of that difference is the point.
    """
    rows = [
        stop_time(39, "TL", 1, "A", T0800),
        stop_time(40, "TL", 2, "Z", T0800 + 5),
        stop_time(41, "TL", 3, "C", T0800 + 10),
    ]
    notices = consecutive(rows, trips=[trip("TL", 15)])
    assert [(row["csvRowNumber1"], row["csvRowNumber2"]) for row in notices] == [(39, 41)]


def test_identical_trips_are_reported_from_the_first_trips_rows():
    """fast1 TF1 and TF2, rows 12 to 15, which are identical trips on one route.

    Two notices, one per trip, and **both name rows 14 and 15**: the group's first trip is
    TF2, and the consecutive scan reads its stop times for every notice it issues. The trip
    fields differ, the stop time fields do not.
    """
    rows = [
        stop_time(12, "TF1", 1, "A", T0800),
        stop_time(13, "TF1", 2, "B", T0800 + 10),
        stop_time(14, "TF2", 1, "A", T0800),
        stop_time(15, "TF2", 2, "B", T0800 + 10),
    ]
    trips = [trip("TF1", 7, route_id="R3"), trip("TF2", 8, route_id="R3")]
    notices = consecutive(rows, trips=trips, routes=[route("R3", 4)])
    assert [(row["tripId"], row["csvRowNumber1"], row["csvRowNumber2"]) for row in notices] == [
        ("TF2", 14, 15),
        ("TF1", 14, 15),
    ]


def test_a_trip_whose_route_is_missing_is_skipped():
    """fast1 TM, rows 42 and 43, on a route id that routes.txt does not declare.

    Nothing, though the pair is as fast as TB's. A broken reference is `foreign_key_violation`
    and upstream leaves it there rather than reporting a speed it cannot threshold.
    """
    rows = [
        stop_time(42, "TM", 1, "A", T0800),
        stop_time(43, "TM", 2, "C", T0800 + 10),
    ]
    assert consecutive(rows, trips=[trip("TM", 16, route_id="R9")]) == []


def test_a_stop_time_whose_trip_is_missing_is_skipped():
    """`tripTable.byTripId` returning empty drops the stop times before any grouping.

    Not in the probe: a trips.txt without the id draws `foreign_key_violation`, which the
    differential would show, but the rule's own silence is what this pins.
    """
    rows = [
        stop_time(2, "TX", 1, "A", T0800),
        stop_time(3, "TX", 2, "C", T0800 + 10),
    ]
    assert consecutive(rows, trips=[trip("T1", 2)]) == []


def test_a_stop_borrows_its_parents_coordinates():
    """fast1 TO, rows 46 and 47, whose second stop is a boarding area inside B.

    It has no coordinates of its own, so the distance resolves through the parent and is B's
    5.56 km. The notice still names the boarding area's own id and name.
    """
    rows = [
        stop_time(46, "TO", 1, "A", T0800),
        stop_time(47, "TO", 2, "CHILD", T0800 + 10),
    ]
    extra = (stop("CHILD", 5, parent="B"),)
    notices = consecutive(rows, trips=[trip("TO", 18)], stop_rows=stops("A", "B", extra=extra))
    assert [(row["stopId2"], row["stopName2"], row["distanceKm"]) for row in notices] == [
        ("CHILD", "Stop CHILD", NEAR_KM)
    ]


def test_a_stop_at_the_origin_is_measured_rather_than_skipped():
    """fast1 TN, rows 44 and 45, whose second stop really sits at latitude 0, longitude 0.

    The one place a plain reading of upstream goes wrong: its "no coordinates" test is `!=`
    against the `S2LatLng.CENTER` *instance*, so only the fallback is caught. A stop at the
    origin compares unequal and is measured, and the jar reports 8652.115181854942 km rather
    than staying silent. That is also not the 8568.438594310714 the transfer rules report for
    the same pair of points, because those go through the other distance overload.
    """
    rows = [
        stop_time(44, "TN", 1, "A", T0800),
        stop_time(45, "TN", 2, "NULL", T0800 + 10),
    ]
    extra = (stop("NULL", 5, 0.0, longitude=0.0),)
    notices = consecutive(rows, trips=[trip("TN", 17)], stop_rows=stops("A", extra=extra))
    assert [(row["distanceKm"], row["speedKph"]) for row in notices] == [
        (ORIGIN_KM, 3114761.4654677794)
    ]


def test_the_code_is_registered_as_a_warning():
    registry.load_rules()
    assert registry.FILE_REGISTRY[CONSECUTIVE].severity is Severity.WARNING


@pytest.mark.parametrize("table", ["stop_times.txt", "trips.txt", "routes.txt", "stops.txt"])
def test_any_of_the_four_tables_failing_silences_the_rule(table):
    """The validator is injected with all four containers, so any one failing gates it."""
    rows = [
        stop_time(2, "T1", 1, "A", T0800),
        stop_time(3, "T1", 2, "C", T0800 + 10),
    ]
    with pytest.raises(DependencyFailed):
        consecutive(rows, unindexable=frozenset({table}))
