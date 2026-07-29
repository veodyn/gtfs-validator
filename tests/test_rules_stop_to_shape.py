"""The four ShapeToStopMatchingValidator codes: what fires, on which stop, with which fields.

Every context value here was measured on a probe feed run through the jar, named in the test that
uses it. The probes are `sm1` (too far), `sm3` (too many matches), `sm4` (out of order) and `sm5`
(too far by user distance); `sm2` is the one that measured the suppression between the two too-far
codes.

The walk that produces them, and the state it carries between trips, is next door in
`test_rules_stop_to_shape_walk`. The split is by responsibility: this half is what a notice says,
that half is which notices exist at all. The geometry underneath both is in
`test_stop_to_shape_geometry` and `test_stop_to_shape_matcher`.
"""

from __future__ import annotations

from shapematchfeed import (
    BUS,
    FAR_SHAPE,
    FAR_STOPS,
    NEAR_STOPS,
    OUT_OF_ORDER,
    RAIL,
    TOO_FAR,
    TOO_FAR_USER_DISTANCE,
    TOO_MANY_MATCHES,
    far_feed,
    feed,
    fire,
    shape,
    stop_times,
    stops,
    trip,
)


def _many_visits(count):
    """A shape that leaves the threshold and returns to the same stop `count` times."""
    points = []
    for visit in range(count):
        points.append((40.0, round(-74.0 + visit * 0.000001, 6)))
        points.append((40.01, round(-74.0 + visit * 0.001, 6)))
        points.append((40.01, round(-74.0 + visit * 0.001 + 0.0005, 6)))
    return points


def test_a_stop_far_from_the_shape_reports_eight_fields():
    """Measured on `sm1`: the jar names S2 with these fields in this order.

    `geoDistanceToShape` is ours rather than the jar's, which reports 333.58530340111884. The
    eleventh digit is divergence 12, amplified by the cross product of two nearly parallel unit
    vectors; the matched location agrees exactly.
    """
    assert fire(TOO_FAR, far_feed()) == [
        {
            "tripCsvRowNumber": 2,
            "shapeId": "SH1",
            "tripId": "T1",
            "stopTimeCsvRowNumber": 3,
            "stopId": "S2",
            "stopName": "Far",
            "match": [40.00000000000236, -73.99500010983789],
            "geoDistanceToShape": 333.5853034003414,
        }
    ]


def test_a_stop_beside_the_shape_is_silent():
    """The negative case for the same feed: S2 moved to 55 m from the shape, inside the 100 m."""
    assert fire(TOO_FAR, far_feed(NEAR_STOPS)) == []


def test_the_threshold_quadruples_for_the_last_stop_of_a_rail_trip():
    """A rail terminus is allowed 400 m, so a 333 m stop is silent when it is first or last.

    Upstream's tolerance for shapes that stop short of a main station. The same feed on a bus
    route reports it, which is what makes the multiplier the cause rather than the geometry.
    """
    far_at_the_end = (
        ("S1", "First", 40.0, -74.0),
        ("S2", "Middle", 40.0, -73.995),
        ("S3", "Far", 40.003, -73.99),
    )
    assert fire(TOO_FAR, far_feed(far_at_the_end, route_type=RAIL)) == []
    assert [row["stopId"] for row in fire(TOO_FAR, far_feed(far_at_the_end, route_type=BUS))] == [
        "S3"
    ]


def test_the_rail_multiplier_does_not_reach_an_intermediate_stop():
    """Only first and last. S2 is neither, so 333 m reports even on rail."""
    assert [row["stopId"] for row in fire(TOO_FAR, far_feed(route_type=RAIL))] == ["S2"]


def test_a_stop_whose_user_distance_points_elsewhere_reports_the_user_distance_code():
    """Measured on `sm5`: S2 sits on the shape but claims a distance 4 km further along it.

    Byte-identical to the jar, distance included. The geo pass is silent here, which is what
    leaves this code free to fire.
    """
    view = feed(
        stops_rows=stops(
            ("S1", "First", 40.0, -74.0),
            ("S2", "Middle", 40.0, -73.95),
            ("S3", "Last", 40.0, -73.9),
        ),
        trips_rows=[trip()],
        times_rows=stop_times("T1", ("S1", 0), ("S2", 8000), ("S3", 8530)),
        shape_rows=shape((40.0, -74.0, 0), (40.0, -73.95, 4265), (40.0, -73.9, 8530)),
    )
    assert fire(TOO_FAR_USER_DISTANCE, view) == [
        {
            "tripCsvRowNumber": 2,
            "shapeId": "SH1",
            "tripId": "T1",
            "stopTimeCsvRowNumber": 3,
            "stopId": "S2",
            "stopName": "Middle",
            "match": [40.00000116906123, -73.90621336438112],
            "geoDistanceToShape": 3729.762603575875,
        }
    ]


def test_a_stop_whose_user_distance_agrees_with_its_position_is_silent():
    """The negative case: the same feed with S2's distance matching where it sits."""
    view = feed(
        stops_rows=stops(
            ("S1", "First", 40.0, -74.0),
            ("S2", "Middle", 40.0, -73.95),
            ("S3", "Last", 40.0, -73.9),
        ),
        trips_rows=[trip()],
        times_rows=stop_times("T1", ("S1", 0), ("S2", 4265), ("S3", 8530)),
        shape_rows=shape((40.0, -74.0, 0), (40.0, -73.95, 4265), (40.0, -73.9, 8530)),
    )
    assert fire(TOO_FAR_USER_DISTANCE, view) == []


def test_the_geo_code_suppresses_the_user_distance_code_for_the_same_stop():
    """Measured on `sm2`: both passes find S2 too far and only the geo code appears.

    The two codes share one set of reported stop ids, so this is not two independent checks that
    happen to agree. Getting it wrong would double every notice on a feed that carries distances.
    """
    view = far_feed(
        FAR_STOPS,
        distances=(0, 426, 853),
        shape_points=((40.0, -74.0, 0), (40.0, -73.995, 426), (40.0, -73.99, 853)),
    )
    assert [row["stopId"] for row in fire(TOO_FAR, view)] == ["S2"]
    assert fire(TOO_FAR_USER_DISTANCE, view) == []


def test_a_stop_the_shape_returns_to_many_times_reports_its_match_count():
    """Measured on `sm3`: twenty-five visits, and the jar counts twenty-five.

    Byte-identical to the jar. Each visit is a vertex on the stop with a 1.1 km excursion after
    it, so every one is a separate local minimum; a zig-zag that stayed within the threshold
    would count once.
    """
    view = feed(
        stops_rows=stops(("S1", "Visited", 40.0, -74.0), ("S2", "Last", 40.01, -73.9755)),
        trips_rows=[trip()],
        times_rows=stop_times("T1", "S1", "S2"),
        shape_rows=shape(*_many_visits(25)),
    )
    assert fire(TOO_MANY_MATCHES, view) == [
        {
            "tripCsvRowNumber": 2,
            "shapeId": "SH1",
            "tripId": "T1",
            "stopTimeCsvRowNumber": 2,
            "stopId": "S1",
            "stopName": "Visited",
            "match": [40.0, -74.0],
            "matchCount": 25,
        }
    ]


def test_twenty_visits_is_not_too_many():
    """The threshold is `> 20`, so exactly twenty is silent. The negative case for the count."""
    view = feed(
        stops_rows=stops(("S1", "Visited", 40.0, -74.0), ("S2", "Last", 40.01, -73.9805)),
        trips_rows=[trip()],
        times_rows=stop_times("T1", "S1", "S2"),
        shape_rows=shape(*_many_visits(20)),
    )
    assert fire(TOO_MANY_MATCHES, view) == []


def test_two_stops_matching_the_shape_backwards_report_both_by_role():
    """Measured on `sm4`: the `1` fields are the stop the matching failed at and the `2` fields its
    predecessor, so `stopTimeCsvRowNumber1` is the larger of the two.

    Byte-identical to the jar, both matched locations included.
    """
    view = feed(
        stops_rows=stops(("S1", "East", 40.0, -73.99), ("S2", "West", 40.0, -74.0)),
        trips_rows=[trip()],
        times_rows=stop_times("T1", "S1", "S2"),
        shape_rows=shape(*FAR_SHAPE),
    )
    assert fire(OUT_OF_ORDER, view) == [
        {
            "tripCsvRowNumber": 2,
            "shapeId": "SH1",
            "tripId": "T1",
            "stopTimeCsvRowNumber1": 3,
            "stopId1": "S2",
            "stopName1": "West",
            "match1": [40.0, -74.0],
            "stopTimeCsvRowNumber2": 2,
            "stopId2": "S1",
            "stopName2": "East",
            "match2": [39.99999999999999, -73.99],
        }
    ]


def test_two_stops_in_shape_order_are_silent():
    """The negative case: the same two stops with their sequence the right way round."""
    view = feed(
        stops_rows=stops(("S1", "West", 40.0, -74.0), ("S2", "East", 40.0, -73.99)),
        trips_rows=[trip()],
        times_rows=stop_times("T1", "S1", "S2"),
        shape_rows=shape(*FAR_SHAPE),
    )
    assert fire(OUT_OF_ORDER, view) == []


def test_a_stop_borrowing_its_parents_coordinates_is_matched_at_them():
    """The coordinates walk up to a parent station, and the reported name does not.

    So a platform with no coordinates and no name of its own is matched at its parent's location
    and reported with an empty `stopName`. Two different lookups over the same row, which is easy
    to collapse into one by accident.
    """
    view = feed(
        stops_rows=[
            {
                "_row_number": 2,
                "stop_id": "S1",
                "stop_name": "First",
                "stop_lat": 40.0,
                "stop_lon": -74.0,
            },
            {
                "_row_number": 3,
                "stop_id": "P",
                "stop_lat": 40.003,
                "stop_lon": -73.995,
                "location_type": 1,
            },
            {"_row_number": 4, "stop_id": "S2", "parent_station": "P"},
            {
                "_row_number": 5,
                "stop_id": "S3",
                "stop_name": "Last",
                "stop_lat": 40.0,
                "stop_lon": -73.99,
            },
        ],
        trips_rows=[trip()],
        times_rows=stop_times("T1", "S1", "S2", "S3"),
        shape_rows=shape(*FAR_SHAPE),
    )
    reported = fire(TOO_FAR, view)
    assert [(row["stopId"], row["stopName"]) for row in reported] == [("S2", "")]
    assert reported[0]["match"] == [40.00000000000236, -73.99500010983789]
