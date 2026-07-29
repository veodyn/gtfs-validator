"""`StopToShapeMatcher`: the assignment search, and what each pass does when it cannot finish.

The matcher's decisions are not visible in a notice's fields, only in which notices exist. These
tests drive it directly so that the control flow can be pinned without a feed: whether every stop is
attempted after one fails, which candidate an out-of-order problem names, and whether the
large-station allowance reaches the user-distance check.
"""

from __future__ import annotations

from gtfs_validator.s2point import to_lat_lng_degrees
from gtfs_validator.stop_to_shape.matcher import (
    MAX_DISTANCE_FROM_STOP_TO_SHAPE_METERS,
    match_using_geo_distance,
    match_using_user_distance,
)
from gtfs_validator.stop_to_shape.matches import ProblemType
from gtfs_validator.stop_to_shape.shape import ShapePoints
from gtfs_validator.stop_to_shape.stops import StopPoints

# A shape along one parallel: three points, 852 m end to end at latitude 40.
SHAPE = ((40.0, -74.0), (40.0, -73.995), (40.0, -73.99))


def _shape(points=SHAPE, distances=None):
    rows = []
    for index, point in enumerate(points):
        row = {"shape_pt_lat": point[0], "shape_pt_lon": point[1], "shape_pt_sequence": index + 1}
        if distances is not None:
            row["shape_dist_traveled"] = distances[index]
        rows.append(row)
    return ShapePoints.from_rows(rows)


def _stops(*entries, large_stations=False):
    """(stop_id, latitude, longitude) or (stop_id, latitude, longitude, user distance)."""
    index = {}
    times = []
    for position, entry in enumerate(entries):
        stop_id, latitude, longitude = entry[0], entry[1], entry[2]
        index[stop_id] = {"stop_id": stop_id, "stop_lat": latitude, "stop_lon": longitude}
        row = {"_row_number": 2 + position, "trip_id": "T1", "stop_id": stop_id}
        if len(entry) > 3:
            row["shape_dist_traveled"] = entry[3]
        times.append(row)
    return StopPoints.from_stop_times(times, index, large_stations)


def _kinds(problems):
    return [problem.type for problem in problems]


def test_every_stop_is_attempted_after_one_fails():
    """`ok &= ...` rather than a break, so two unmatchable stops draw two problems.

    A `break` would report the first and hide the second, which is the difference between a feed's
    worth of notices and one.
    """
    stops = _stops(
        ("S1", 40.0, -74.0),
        ("S2", 40.01, -73.997),
        ("S3", 40.02, -73.994),
    )
    result = match_using_geo_distance(stops, _shape())
    assert _kinds(result.problems) == [
        ProblemType.STOP_TOO_FAR_FROM_SHAPE,
        ProblemType.STOP_TOO_FAR_FROM_SHAPE,
    ]
    assert [problem.stop_time["stop_id"] for problem in result.problems] == ["S2", "S3"]


def test_a_failed_geo_pass_returns_no_matches():
    """The matches list stays empty when any stop has no candidates, even for the stops that did.

    Which is why nothing downstream can read a partial assignment: upstream returns the list it was
    holding, and it was holding nothing.
    """
    stops = _stops(("S1", 40.0, -74.0), ("S2", 40.01, -73.997))
    assert match_using_geo_distance(stops, _shape()).matches == []


def test_a_matched_trip_reports_no_problems():
    """The middle stop matches segment **0**, not segment 1, and the jar agrees.

    It sits exactly on the vertex the two segments share, and `keepBestMatch` compares with a
    strict `<`, so the segment reached first keeps it. The indices were measured with
    `ShapePoints.matchesFromLocation` in the jar rather than reasoned about: the intuitive answer is
    that a stop on a vertex belongs to the segment starting there.
    """
    stops = _stops(("S1", 40.0, -74.0), ("S2", 40.0, -73.995), ("S3", 40.0, -73.99))
    result = match_using_geo_distance(stops, _shape())
    assert result.problems == []
    assert [match.index for match in result.matches] == [0, 0, 1]


def test_stops_in_reverse_order_report_the_pair_by_role():
    """The `1` role is the stop the search failed at, the `2` role its predecessor."""
    stops = _stops(("S1", 40.0, -73.99), ("S2", 40.0, -74.0))
    problems = match_using_geo_distance(stops, _shape()).problems
    assert _kinds(problems) == [ProblemType.STOPS_MATCH_OUT_OF_ORDER]
    assert problems[0].stop_time["stop_id"] == "S2"
    assert problems[0].previous_stop_time["stop_id"] == "S1"


def test_only_one_out_of_order_problem_is_reported_per_trip():
    """The search returns at the first infeasible stop, so a wholly reversed trip reports once."""
    stops = _stops(("S1", 40.0, -73.99), ("S2", 40.0, -73.995), ("S3", 40.0, -74.0))
    problems = match_using_geo_distance(stops, _shape()).problems
    assert len(problems) == 1
    assert problems[0].stop_time["stop_id"] == "S2"


def test_an_out_of_order_problem_names_the_previous_stops_assigned_candidate():
    """Two different rules for the two matches, and they are not interchangeable.

    The failing stop's match is its *closest* candidate. The previous stop's is whichever the
    best-scoring surviving assignment chose, which is a place the search actually used. Reporting
    the previous stop's closest candidate instead would name somewhere the matching never
    considered.
    """
    stops = _stops(("S1", 40.0, -73.99), ("S2", 40.0, -74.0))
    problem = match_using_geo_distance(stops, _shape()).problems[0]
    assert to_lat_lng_degrees(problem.match.location) == (40.0, -74.0)
    assert to_lat_lng_degrees(problem.previous_match.location) == (39.99999999999999, -73.99)


def test_two_stops_at_the_same_place_on_the_shape_are_in_order():
    """Feasibility is `previous > candidate`, so an exact tie is allowed.

    Two stops sharing a location is ordinary in a feed, and reading the comparison as `>=` would
    report every such pair as out of order.
    """
    stops = _stops(("S1", 40.0, -73.995), ("S2", 40.0, -73.995))
    assert match_using_geo_distance(stops, _shape()).problems == []


def test_the_user_distance_pass_reports_a_stop_whose_distance_points_elsewhere():
    stops = _stops(("S1", 40.0, -74.0, 0.0), ("S2", 40.0, -73.995, 850.0))
    problems = match_using_user_distance(stops, _shape(distances=(0.0, 426.0, 852.0))).problems
    assert _kinds(problems) == [ProblemType.STOP_TOO_FAR_FROM_SHAPE]
    assert problems[0].stop_time["stop_id"] == "S2"


def test_the_large_station_allowance_does_not_reach_the_user_distance_check():
    """A rail terminus tolerated at 400 m by geometry is judged at 100 m by user distance.

    So the same stop on the same feed can be silent in one pass and reported in the other, and the
    multiplier is the reason. `isValidStopsToShapeMatchFromUserDistance` reads the plain setting.
    """
    stops = _stops(("S1", 40.0, -74.0, 0.0), ("S2", 40.0, -73.995, 850.0), large_stations=True)
    shape = _shape(distances=(0.0, 426.0, 852.0))
    # Large station or not, the user-distance pass reports it.
    assert _kinds(match_using_user_distance(stops, shape).problems) == [
        ProblemType.STOP_TOO_FAR_FROM_SHAPE
    ]
    # The geo pass finds S2 sitting on the shape, so it has nothing to say either way; the
    # difference the multiplier makes to *that* pass is tested in the rule tests, where a feed can
    # carry a route type.
    assert match_using_geo_distance(stops, shape).problems == []


def test_a_stop_with_no_user_distance_falls_back_to_geometry():
    """And if that fails, the whole pass abandons with what it has.

    The early return is upstream's, and it means one unmatchable stop can hide a later stop's
    user-distance problem: S3 below would be reported, and is not.
    """
    stops = _stops(
        ("S1", 40.0, -74.0, 0.0),
        ("S2", 40.01, -73.997),
        ("S3", 40.0, -73.995, 850.0),
    )
    problems = match_using_user_distance(stops, _shape(distances=(0.0, 426.0, 852.0))).problems
    assert _kinds(problems) == [ProblemType.STOP_TOO_FAR_FROM_SHAPE]
    assert problems[0].stop_time["stop_id"] == "S2"


def test_a_stop_with_no_user_distance_that_matches_geometrically_continues():
    """The other side of that fallback: a matchable distance-less stop does not stop the pass."""
    stops = _stops(
        ("S1", 40.0, -74.0, 0.0),
        ("S2", 40.0, -73.995),
        ("S3", 40.0, -73.99, 852.0),
    )
    assert match_using_user_distance(stops, _shape(distances=(0.0, 426.0, 852.0))).problems == []


def test_an_empty_stop_sequence_matches_nothing():
    assert match_using_geo_distance(_stops(), _shape()).problems == []
    assert match_using_user_distance(_stops(), _shape()).problems == []


def test_an_empty_shape_matches_nothing():
    """Guarded before the search rather than inside it, so no problem is reported at all.

    A stop cannot be "too far" from a shape with no points: there is no distance to report.
    """
    stops = _stops(("S1", 40.0, -74.0))
    assert match_using_geo_distance(stops, _shape(points=())).problems == []


def test_the_threshold_is_the_documented_hundred_metres():
    """Pinned so a change to the constant is a failing test rather than a silent retune."""
    assert MAX_DISTANCE_FROM_STOP_TO_SHAPE_METERS == 100.0
