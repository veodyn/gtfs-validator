"""`geometry.overlaps` against verdicts taken from the JTS in the pinned jar.

The generated corpus lives in `tools/diff_overlaps_against_jts.py`, which needs java. These are
its named cases pinned so the suite covers the predicate on a machine without one, and they are
chosen the way that file chooses them: each is a *rule* JTS applies rather than a shape with a
comfortable margin.

`overlaps` is the DE-9IM predicate. Three of these are the ones a reading of the English word
gets wrong, and all three are false: containment, a shared edge, and two identical polygons.
"""

from __future__ import annotations

import pytest

from gtfs_validator.geometry.overlaps import (
    BOUNDARY,
    INSIDE,
    OUTSIDE,
    classify,
    polygons_overlap,
    to_exact,
)


def square(x, y, size):
    return [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]]


def with_hole(x, y, size, hole):
    inset = (size - hole) / 2
    hx, hy = x + inset, y + inset
    return [
        square(x, y, size)[0],
        [[hx, hy], [hx, hy + hole], [hx + hole, hy + hole], [hx + hole, hy], [hx, hy]],
    ]


UNIT = square(0.0, 0.0, 2.0)
RING = with_hole(0.0, 0.0, 6.0, 2.0)

# (name, A, B, what JTS answers). Measured by tools/jts/CheckOverlaps.
CASES = [
    ("identical", UNIT, square(0.0, 0.0, 2.0), False),
    ("disjoint", UNIT, square(5.0, 5.0, 2.0), False),
    ("shared-edge", UNIT, square(2.0, 0.0, 2.0), False),
    ("shared-vertex", UNIT, square(2.0, 2.0, 2.0), False),
    ("properly-crossing", UNIT, square(1.0, 1.0, 2.0), True),
    ("contained", UNIT, square(0.5, 0.5, 1.0), False),
    ("contained-touching-edge", UNIT, square(0.0, 0.5, 1.0), False),
    ("contains", square(0.5, 0.5, 1.0), UNIT, False),
    ("triangle-crossing", UNIT, [[[1.0, 1.0], [3.0, 1.0], [1.0, 3.0], [1.0, 1.0]]], True),
    ("triangle-inside", UNIT, [[[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.25, 0.25]]], False),
    ("sliver-crossing", UNIT, [[[1.0, 0.5], [5.0, 0.5], [5.0, 0.6], [1.0, 0.6], [1.0, 0.5]]], True),
    ("hole-vs-inner", RING, square(2.5, 2.5, 1.0), False),
    ("hole-vs-crossing", RING, square(1.0, 2.5, 2.0), True),
    ("hole-edge-shared", RING, square(2.0, 2.0, 2.0), False),
    ("hole-vs-hole", RING, with_hole(1.0, 1.0, 6.0, 2.0), True),
]


@pytest.mark.parametrize(("name", "first", "second", "expected"), CASES)
def test_the_predicate_matches_jts(name, first, second, expected):
    assert polygons_overlap(to_exact(first), to_exact(second)) is expected


@pytest.mark.parametrize(("name", "first", "second", "expected"), CASES)
def test_the_predicate_is_symmetric(name, first, second, expected):
    """Only A's boundary is walked, so the reverse direction is a different computation.

    JTS's `overlaps` is symmetric and so is the geometry it describes, but nothing in this
    implementation makes that true by construction: the answer comes from where A's boundary
    falls relative to B. Asserting both directions is what turns that from an argument into a
    checked property.
    """
    assert polygons_overlap(to_exact(second), to_exact(first)) is expected


def test_a_polygon_never_overlaps_itself():
    """The degenerate case of `identical`, and the one a caller is most likely to hit.

    A stop time naming the same zone twice is skipped by the rule before it gets here, but the
    predicate answers correctly on its own rather than relying on that.
    """
    assert polygons_overlap(to_exact(UNIT), to_exact(UNIT)) is False


def test_an_empty_polygon_overlaps_nothing():
    assert polygons_overlap([], to_exact(UNIT)) is False
    assert polygons_overlap(to_exact(UNIT), []) is False


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((1.0, 1.0), INSIDE),
        ((0.0, 0.0), BOUNDARY),
        ((1.0, 0.0), BOUNDARY),
        ((3.0, 1.0), OUTSIDE),
        ((-1.0, 1.0), OUTSIDE),
    ],
)
def test_classify_separates_inside_boundary_and_outside(point, expected):
    """Three states, not two. A point *on* the boundary is neither in nor out.

    That distinction is the whole predicate: a polygon boundary lying along another's boundary
    is what tells a shared edge apart from a crossing.
    """
    from fractions import Fraction

    exact = (Fraction(point[0]), Fraction(point[1]))
    assert classify(exact, to_exact(UNIT)) == expected


def test_a_hole_makes_its_inside_outside_and_its_edge_boundary():
    """A polygon is its shell minus its holes, so a hole inverts both answers within it."""
    from fractions import Fraction

    inside_hole = (Fraction(3), Fraction(3))
    on_hole_edge = (Fraction(2), Fraction(3))
    in_the_ring = (Fraction(1), Fraction(3))
    assert classify(inside_hole, to_exact(RING)) == OUTSIDE
    assert classify(on_hole_edge, to_exact(RING)) == BOUNDARY
    assert classify(in_the_ring, to_exact(RING)) == INSIDE
