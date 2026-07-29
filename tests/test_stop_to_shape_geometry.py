"""`ShapePoints` and `StopPoints`: the two distances a shape carries, and the per-stop threshold.

These are the constructions that look like arithmetic and are not. The user distance is a running
maximum rather than the row's value, the geo distance uses the haversine where the rest of the
matching uses the vector form, and the large-station flag is computed against a list that is still
being built.
"""

from __future__ import annotations

import math

from gtfs_validator.s2point import to_lat_lng_degrees, to_point
from gtfs_validator.stop_to_shape.shape import ShapePoints
from gtfs_validator.stop_to_shape.stops import (
    RAIL_ROUTE_TYPE,
    StopPoints,
    large_stations_for_route_type,
)


def _shape(*points):
    rows = []
    for index, point in enumerate(points):
        row = {"shape_pt_lat": point[0], "shape_pt_lon": point[1], "shape_pt_sequence": index + 1}
        if len(point) > 2:
            row["shape_dist_traveled"] = point[2]
        rows.append(row)
    return ShapePoints.from_rows(rows)


def _stop_time(stop_id, distance=None):
    row = {"_row_number": 2, "trip_id": "T1", "stop_id": stop_id}
    if distance is not None:
        row["shape_dist_traveled"] = distance
    return row


STOPS = {
    "A": {"stop_id": "A", "stop_lat": 40.0, "stop_lon": -74.0},
    "B": {"stop_id": "B", "stop_lat": 40.0, "stop_lon": -73.99},
}


def test_the_geo_distance_accumulates_along_the_shape():
    """Each hop's haversine, summed. 0.005 degrees of longitude at latitude 40 is about 426 m."""
    shape = _shape((40.0, -74.0), (40.0, -73.995), (40.0, -73.99))
    assert [point.geo_distance for point in shape.points] == [
        0.0,
        425.9019467394562,
        851.8038934799961,
    ]


def test_the_geo_distance_uses_the_haversine_and_not_the_vector_form():
    """The two `getDistanceMeters` overloads disagree in the last digits, and this one is the
    haversine because upstream passes an `S2LatLng` here.

    Pinned by computing the same hop both ways: they differ, so the choice is observable and a
    port that reached for the wrong overload would be caught here rather than by a 1e-11 wobble in
    a reported distance.
    """
    from gtfs_validator.s2earth import distance_meters, vector_distance_meters

    haversine = distance_meters(40.0, -74.0, 40.0, -73.995)
    vector = vector_distance_meters(to_point(40.0, -74.0), to_point(40.0, -73.995))
    assert haversine != vector
    assert _shape((40.0, -74.0), (40.0, -73.995)).points[1].geo_distance == haversine


def test_the_user_distance_is_a_running_maximum():
    """A shape whose `shape_dist_traveled` decreases carries the larger value forward.

    So the search for a user distance stays monotonic even on a feed that is not, and the third
    point below reports 500 rather than the 300 its own row gives.
    """
    shape = _shape((40.0, -74.0, 0), (40.0, -73.995, 500), (40.0, -73.99, 300))
    assert [point.user_distance for point in shape.points] == [0.0, 500.0, 500.0]


def test_a_blank_shape_dist_traveled_reads_as_zero_rather_than_being_skipped():
    """`shapeDistTraveled()` on an unset double is 0.0, and the running maximum keeps the rest."""
    shape = _shape((40.0, -74.0, 10), (40.0, -73.995), (40.0, -73.99, 20))
    assert [point.user_distance for point in shape.points] == [10.0, 10.0, 20.0]


def test_a_nan_user_distance_poisons_every_later_point_as_math_max_does():
    """`Math.max` returns NaN if either argument is NaN, and Python's `max` does not.

    Measured against Java: accumulating `[0, NaN, 1000]` gives `0, NaN, NaN` there and
    `0, 0, 1000` with Python's `max`, because every comparison against NaN is false and `max`
    keeps whichever argument came first. That is not a lost digit. The shape's last point ends up
    with a positive user distance instead of a NaN one, so `has_user_distance` is True where
    upstream's is False, and the entire user-distance pass runs on one side only.

    A NaN `shape_dist_traveled` is reachable: see the `trip_shape_nan_max` note in
    known-divergences entry 12.
    """
    shape = _shape((40.0, -74.0, 0.0), (40.0, -73.99, float("nan")), (40.0, -73.98, 1000.0))
    distances = [point.user_distance for point in shape.points]
    assert distances[0] == 0.0
    assert math.isnan(distances[1])
    assert math.isnan(distances[2])
    # The consequence, which is the reason the helper exists rather than a tidier `max`.
    assert not shape.has_user_distance()


def test_has_user_distance_reads_the_last_point_only():
    """`Iterables.getLast`, so a shape that gives up halfway counts as having no user distance.

    It cannot be otherwise given the running maximum: a positive value anywhere makes every later
    point positive too, so the last point is the whole answer. Pinned because the reverse reading,
    "any point carries one", is the natural one and gives a different answer for the all-zero
    shape below.
    """
    assert _shape((40.0, -74.0, 0), (40.0, -73.99, 100)).has_user_distance()
    assert not _shape((40.0, -74.0, 0), (40.0, -73.99, 0)).has_user_distance()
    assert not _shape((40.0, -74.0), (40.0, -73.99)).has_user_distance()
    assert not _shape().has_user_distance()


def test_a_one_point_shape_still_matches():
    """The segment loop cannot see a shape with no segments, so a single point is special-cased.

    Without it the match would come back empty and a stop beside a one-point shape would be
    reported as a perfect match at the origin rather than as too far.
    """
    match = _shape((40.0, -74.0)).match_from_location(to_point(40.003, -74.0))
    assert match.has_best_match()
    assert to_lat_lng_degrees(match.location) == (40.0, -74.0)
    assert match.geo_distance_to_shape == 333.5853035322396


def test_an_empty_shape_matches_nothing():
    """No points at all: no best match, and its distance is infinity rather than zero.

    Which is why the too-far test is `> maxDistance` on a real distance and cannot be reached
    here: infinity is not a distance any notice reports.
    """
    match = _shape().match_from_location(to_point(40.0, -74.0))
    assert not match.has_best_match()
    assert match.geo_distance_to_shape == math.inf


def test_a_straight_run_of_shape_is_not_one_candidate_per_segment():
    """A stop beside four collinear segments has two local minima, not four and not one.

    This test first asserted one, on the reasoning that a straight run cannot have two minima. The
    jar says two, and the reason is worth keeping: the stop sits directly above vertex 2, and the
    perpendicular foot on the segment *before* that vertex is 7e-11 m closer than the vertex
    itself. The loop therefore sees the shape recede and then close again, and banks a match. So
    the count is a count of local minima in floating-point arithmetic, not in geometry.

    Confirmed against `ShapePoints.matchesFromLocation` in the jar, which returns the same two
    indices. `tools/diff_shape_matching_against_jar.py` runs that comparison over a corpus.
    """
    shape = _shape(*[(40.0, -74.0 + step * 0.001) for step in range(5)])
    matches = shape.matches_from_location(to_point(40.0005, -73.998), 100.0)
    assert [match.index for match in matches] == [1, 2]


def test_a_stop_beside_a_run_it_is_not_above_is_one_candidate():
    """Moved half a vertex spacing along, the same run gives one candidate.

    Which is what makes the two-candidate case above about the vertex rather than about the run.
    """
    shape = _shape(*[(40.0, -74.0 + step * 0.001) for step in range(5)])
    assert len(shape.matches_from_location(to_point(40.0005, -73.9985), 100.0)) == 1


def test_each_excursion_beyond_the_threshold_banks_a_candidate():
    """Three visits with a 1.1 km excursion between them give three candidates.

    The excursion is what banks the running match: a shape that stays inside the threshold the
    whole way is one candidate however much it wanders.
    """
    points = []
    for visit in range(3):
        points.append((40.0, -74.0 + visit * 0.000001))
        points.append((40.01, -74.0 + visit * 0.001))
        points.append((40.01, -74.0 + visit * 0.001 + 0.0005))
    assert len(_shape(*points).matches_from_location(to_point(40.0, -74.0), 100.0)) == 3


def test_a_closest_point_match_carries_no_user_distance():
    """`fillLocationMatch` sets it to zero even on a shape whose points all have one.

    So a stop matched by geometry reports a user distance of zero rather than the interpolated
    value its position implies.
    """
    shape = _shape((40.0, -74.0, 100), (40.0, -73.99, 200))
    match = shape.match_from_location(to_point(40.0, -73.995))
    assert match.user_distance == 0.0
    # The distance *along* the shape is filled in, which is the field the assignment search orders
    # by, so the two are easy to confuse.
    assert match.geo_distance == 425.9019465725542


def test_a_user_distance_before_the_shape_starts_matches_the_first_vertex():
    """`nextIndex <= 0` returns a fraction of zero, so the match is the vertex itself."""
    shape = _shape((40.0, -74.0, 100), (40.0, -73.99, 200))
    match = shape.match_from_user_dist(50.0, 0, to_point(40.0, -74.0))
    assert match.index == 0
    assert to_lat_lng_degrees(match.location) == (40.0, -74.0)


def test_a_user_distance_past_the_end_matches_the_last_vertex():
    """`previousIndex + 1 >= size` is the other zero-fraction case."""
    shape = _shape((40.0, -74.0, 100), (40.0, -73.99, 200))
    match = shape.match_from_user_dist(500.0, 0, to_point(40.0, -73.99))
    assert match.index == 1
    # Not exactly (40.0, -73.99): the vertex is a unit vector converted back, and the round trip
    # through two trigonometric conversions does not preserve the input.
    assert to_lat_lng_degrees(match.location) == (40.00000000000001, -73.99)


def test_a_user_distance_between_two_vertices_interpolates():
    shape = _shape((40.0, -74.0, 0), (40.0, -73.99, 100))
    match = shape.match_from_user_dist(50.0, 0, to_point(40.0, -73.995))
    assert match.index == 0
    assert to_lat_lng_degrees(match.location) == (40.00000010742586, -73.995)
    assert match.user_distance == 50.0


def test_two_vertices_with_near_equal_distances_do_not_interpolate():
    """`nearByFractionOrMargin` guards the ratio of two nearly equal numbers.

    Its margin is 3.2e-8, so two distances 1e-9 apart are "the same" and the match snaps to the
    earlier vertex instead of dividing by a difference that is mostly rounding error.
    """
    shape = _shape((40.0, -74.0, 100.0), (40.0, -73.99, 100.000000001), (40.0, -73.98, 200.0))
    match = shape.match_from_user_dist(100.0000000005, 0, to_point(40.0, -73.99))
    # The *previous* vertex, not the next one: the guard returns a fraction of zero against the
    # index the search had already reached.
    assert match.index == 0
    assert to_lat_lng_degrees(match.location) == (40.0, -74.0)


def test_the_first_and_last_stop_of_a_rail_trip_are_large_stations():
    times = [_stop_time("A"), _stop_time("B"), _stop_time("A")]
    points = StopPoints.from_stop_times(times, STOPS, large_stations=True).points
    assert [point.is_large_station for point in points] == [True, False, True]


def test_no_stop_is_a_large_station_on_a_bus_trip():
    times = [_stop_time("A"), _stop_time("B"), _stop_time("A")]
    points = StopPoints.from_stop_times(times, STOPS, large_stations=False).points
    assert [point.is_large_station for point in points] == [False, False, False]


def test_both_stops_of_a_two_stop_rail_trip_are_large_stations():
    """The first and the last, which on a two-stop trip is both of them.

    The flag is computed before the row is appended, so the second stop sees `len(points) == 1`
    against `len(stop_times) - 1 == 1` and qualifies. Appending first would make the test
    `len(points) == 2` and silently exclude it.
    """
    points = StopPoints.from_stop_times(
        [_stop_time("A"), _stop_time("B")], STOPS, large_stations=True
    ).points
    assert [point.is_large_station for point in points] == [True, True]


def test_a_stop_that_resolves_to_nothing_sits_at_the_origin():
    """`S2LatLng.CENTER`, and the point is kept rather than dropped.

    Dropping it would renumber the sequence and change which stops are first and last, so an
    unresolvable stop in the middle of a trip would move the large-station allowance.
    """
    points = StopPoints.from_stop_times([_stop_time("MISSING")], STOPS, large_stations=False).points
    assert to_lat_lng_degrees(points[0].location) == (0.0, 0.0)


def test_only_the_rail_route_type_gets_the_large_station_allowance():
    assert large_stations_for_route_type(RAIL_ROUTE_TYPE)
    assert not large_stations_for_route_type(3)
    # A route_type outside the enum survives typing with a warning, so this is reachable.
    assert not large_stations_for_route_type(99)
    assert not large_stations_for_route_type(None)
