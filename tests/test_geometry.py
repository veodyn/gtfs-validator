"""The geometry engine behind `invalid_geometry`.

Every expectation here is a verdict from the JTS inside the pinned jar, produced by
`tools/diff_geometry_against_jts.py`. That tool is the real check on this code: it runs a
curated corpus plus a seeded random one through both implementations and compares every
verdict. These tests pin the cases that cost something to get right, so a regression names
the behaviour rather than a corpus index.
"""

from __future__ import annotations

import pytest

from gtfs_validator.geometry import geometry_message
from gtfs_validator.geometry.validity import (
    DISCONNECTED_INTERIOR,
    HOLE_OUTSIDE_SHELL,
    INVALID_COORDINATE,
    NESTED_HOLES,
    NESTED_SHELLS,
    RING_SELF_INTERSECTION,
    SELF_INTERSECTION,
    TOO_FEW_POINTS,
    construction_message,
    validate_multipolygon,
    validate_polygon,
)

SQUARE = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]
BIG_SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]


def ring(*points):
    return [(float(x), float(y)) for x, y in points]


def test_a_plain_square_is_valid():
    assert validate_polygon([SQUARE]) is None
    # Winding order does not matter to validity.
    assert validate_polygon([list(reversed(SQUARE))]) is None


@pytest.mark.parametrize(
    ("name", "rings", "expected"),
    [
        ("bowtie", [ring((0, 0), (2, 2), (2, 0), (0, 2), (0, 0))], SELF_INTERSECTION),
        ("collapsed", [ring((0, 0), (1, 1), (1, 1), (0, 0))], TOO_FEW_POINTS),
        (
            "hole_outside",
            [SQUARE, ring((10, 10), (11, 10), (11, 11), (10, 10))],
            HOLE_OUTSIDE_SHELL,
        ),
        (
            "nested_holes",
            [
                BIG_SQUARE,
                ring((1, 1), (8, 1), (8, 8), (1, 8), (1, 1)),
                ring((2, 2), (7, 2), (7, 7), (2, 7), (2, 2)),
            ],
            NESTED_HOLES,
        ),
        (
            "hole_crossing_shell",
            [SQUARE, ring((3, 3), (6, 3), (6, 6), (3, 6), (3, 3))],
            SELF_INTERSECTION,
        ),
        (
            "pinched",
            [BIG_SQUARE, ring((0, 5), (5, 4), (10, 5), (5, 6), (0, 5))],
            DISCONNECTED_INTERIOR,
        ),
        ("nan", [ring((0, 0), (4, 0), (float("nan"), 4), (0, 4), (0, 0))], INVALID_COORDINATE),
    ],
)
def test_the_reported_error_is_the_jars(name, rings, expected):
    assert validate_polygon(rings) == expected, name


def test_a_repeated_point_is_valid():
    """A zero-length segment touches its neighbour at a point, and treating that as a
    self-touch reported nine valid rings in the random corpus. JTS removes repeated points
    before noding, so this ring is valid rather than self-intersecting."""
    assert validate_polygon([ring((0, 0), (4, 0), (4, 0), (4, 4), (0, 4), (0, 0))]) is None


def test_too_few_points_counts_coordinates_not_distinct_ones():
    """The bound is four coordinates after collapsing *consecutive* duplicates.

    Counting distinct points instead would call both of these too few, and the jar reports
    a self-intersection for the second: it keeps five coordinates because none of its
    duplicates are consecutive.
    """
    assert validate_polygon([ring((0, 0), (1, 1), (1, 1), (0, 0))]) == TOO_FEW_POINTS
    # The jar calls this one SELF_INTERSECTION and we call it RING_SELF_INTERSECTION: it is
    # one of the shapes covered by divergence 8, so asserting either name would encode a
    # position this code does not hold. What the test is here to pin is that it is *not*
    # too-few-points, because it keeps five coordinates.
    assert validate_polygon([ring((0, 0), (5, 0), (0, 0), (5, 0), (0, 0))]) in (
        SELF_INTERSECTION,
        RING_SELF_INTERSECTION,
    )
    # Three coordinates is enough to build but not to be valid; four with three distinct
    # points is valid.
    assert validate_polygon([ring((0, 0), (1, 0), (0, 0))]) == TOO_FEW_POINTS
    assert validate_polygon([ring((0, 0), (1, 0), (1, 1), (0, 0))]) is None


def test_one_touch_is_fine_and_two_pinch_the_interior():
    """The connectivity test is a cycle in the touch graph, so the count matters: a hole
    touching the shell once is valid, twice is a disconnected interior, and two holes
    touching each other once is valid."""
    once = [BIG_SQUARE, ring((0, 5), (5, 4), (5, 6), (0, 5))]
    twice = [BIG_SQUARE, ring((0, 5), (5, 4), (10, 5), (5, 6), (0, 5))]
    two_holes = [
        BIG_SQUARE,
        ring((1, 1), (5, 1), (5, 5), (1, 5), (1, 1)),
        ring((5, 5), (9, 5), (9, 9), (5, 9), (5, 5)),
    ]
    assert validate_polygon(once) is None
    assert validate_polygon(twice) == DISCONNECTED_INTERIOR
    assert validate_polygon(two_holes) is None


def test_a_member_inside_another_members_hole_is_valid():
    """Nested shells are invalid, but a shell sitting in another member's *hole* is not:
    the hole is not part of that member, so the interiors stay disjoint."""
    outer = [BIG_SQUARE, ring((2, 2), (8, 2), (8, 8), (2, 8), (2, 2))]
    inner = [ring((3, 3), (7, 3), (7, 7), (3, 7), (3, 3))]
    assert validate_multipolygon([outer, inner]) is None
    assert validate_multipolygon([[BIG_SQUARE], inner]) == NESTED_SHELLS


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        (0, None),
        (1, "Invalid number of points in LineString (found 1 - must be 0 or >= 2)"),
        (2, "Invalid number of points in LinearRing (found 2 - must be 0 or >= 3)"),
    ],
)
def test_construction_refusals_carry_the_jars_wording(points, expected):
    assert construction_message([(0.0, 0.0)] * points) == expected


def test_an_unclosed_ring_is_a_construction_refusal():
    assert construction_message(ring((0, 0), (4, 0), (4, 4), (0, 4))) == (
        "Points of LinearRing do not form a closed linestring"
    )


def test_the_message_comes_from_the_generated_table():
    """The seam the GeoJSON parser uses, in GeoJSON's own coordinate shape."""
    bowtie = [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]
    assert geometry_message("Polygon", bowtie) == "Self-intersection"
    assert geometry_message("Polygon", [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]]) is None
    # A third ordinate is ignored, as upstream ignores anything past the second.
    with_elevation = [[[0, 0, 12], [4, 0, 12], [4, 4, 12], [0, 4, 12], [0, 0, 12]]]
    assert geometry_message("Polygon", with_elevation) is None
