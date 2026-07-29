"""The segment grid must be invisible: same matches, same floats, same order.

The naive full scan is the oracle. The grid-backed front doors must agree exactly,
including which segment index wins an exact tie, on geometries built to hit the edge
cases: a stop near one segment, near a long straight run, a shape passing twice, a
shape entirely out of threshold, a one-point shape, duplicated rows (real feeds carry
them, and they make exact distance ties reachable), the antimeridian, and a pole.
"""

from gtfs_validator.s2point import to_point
from gtfs_validator.stop_to_shape.shape import ShapePoints


def _shape(coords):
    rows = [
        {"shape_pt_lat": lat, "shape_pt_lon": lon, "shape_dist_traveled": None}
        for lat, lon in coords
    ]
    return ShapePoints.from_rows(rows)


def _zigzag(n, lat0=47.0, lon0=8.0, step=0.001):
    return [(lat0 + (i % 2) * step, lon0 + i * step) for i in range(n)]


CASES = [
    ("single segment", _shape([(47.0, 8.0), (47.0, 8.01)]), (47.0005, 8.005)),
    (
        "long straight run",
        _shape([(47.0, 8.0 + i * 0.0005) for i in range(200)]),
        (47.0004, 8.02),
    ),
    (
        "passes twice",
        _shape([(47.0, 8.0), (47.0, 8.02), (47.001, 8.02), (47.001, 8.0)]),
        (47.0005, 8.01),
    ),
    ("all far", _shape(_zigzag(50)), (48.0, 9.0)),
    ("one point", _shape([(47.0, 8.0)]), (47.1, 8.1)),
    (
        "duplicate rows, tied distances",
        _shape([(47.0, 8.0), (47.0, 8.01), (47.0, 8.0), (47.0, 8.01)]),
        (47.0001, 8.005),
    ),
    ("antimeridian", _shape([(10.0, 179.99), (10.0, -179.99)]), (10.0005, 180.0)),
    ("near pole", _shape([(89.9, 0.0), (89.9, 90.0)]), (89.95, 45.0)),
    ("far but findable", _shape(_zigzag(50)), (47.05, 8.02)),
    # A review's reproduction: long east-west segments at high latitude are arcs that
    # bow poleward of their endpoints' bounding box, and a stop can sit nanometres
    # from the arc while far outside the box. Long segments now disable the grid,
    # and the oracle proves the fallback answers exactly.
    (
        "great-circle bulge",
        _shape([(69.0, 1.0), (60.0, 1.0), (60.0, -50.0), (60.0, 50.0)]),
        (69.63942512488693, 0.0),
    ),
    # The same review's second reproduction: a shape hard against +180 queried by a
    # stop just past -180. The shape stays under the enable span, so the query box
    # must wrap by a full turn to find it.
    (
        "antimeridian query wrap",
        _shape([(10.0, 179.99975), (10.0001, 179.99975)] * 25),
        (10.0, -179.99975),
    ),
]


def _as_tuples(matches):
    return [
        (m.index, m.geo_distance, m.user_distance, m.geo_distance_to_shape, m.location)
        for m in matches
    ]


def test_threshold_matches_are_identical():
    for name, shape, (lat, lon) in CASES:
        stop = to_point(lat, lon)
        for max_distance in (100.0, 400.0):
            naive = shape._matches_from_location_scan(stop, max_distance)
            fast = shape.matches_from_location(stop, max_distance)
            assert _as_tuples(fast) == _as_tuples(naive), (name, max_distance)


def test_closest_match_is_identical():
    for name, shape, (lat, lon) in CASES:
        stop = to_point(lat, lon)
        naive = shape._match_from_location_scan(stop)
        fast = shape.match_from_location(stop)
        assert naive.index == fast.index, name
        assert naive.geo_distance_to_shape == fast.geo_distance_to_shape, name
        assert naive.location == fast.location, name
        assert naive.geo_distance == fast.geo_distance, name
        assert naive.user_distance == fast.user_distance, name
