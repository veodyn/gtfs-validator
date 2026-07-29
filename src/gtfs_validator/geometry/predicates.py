"""Exact geometric predicates for the polygon validity checks.

JTS uses double-double arithmetic (`CGAlgorithmsDD`) to make orientation robust. Here the
same job is done with `fractions.Fraction`, which is exact rather than merely extended:
every coordinate a feed can carry is a float, and a float is a rational, so orientation
and intersection are decided without error.

That is at least as accurate as the jar, and the one way it could diverge is worth
stating plainly: on a shape where double-double rounding gives JTS the wrong answer, we
would give the right one and disagree. No such case has been found in the corpus, and
looking for one is a matter of running more shapes through
`tools/diff_geometry_against_jts.py`, not of reading this file.
"""

from __future__ import annotations

from fractions import Fraction

Point = tuple[float, float]
Segment = tuple[Point, Point]

COLLINEAR = 0
COUNTERCLOCKWISE = 1
CLOCKWISE = -1


def _exact(value: float) -> Fraction:
    return Fraction(value)


def orientation(a: Point, b: Point, c: Point) -> int:
    """The sign of the cross product, exactly: which side of ab the point c lies on."""
    area = (_exact(b[0]) - _exact(a[0])) * (_exact(c[1]) - _exact(a[1])) - (
        _exact(b[1]) - _exact(a[1])
    ) * (_exact(c[0]) - _exact(a[0]))
    if area > 0:
        return COUNTERCLOCKWISE
    if area < 0:
        return CLOCKWISE
    return COLLINEAR


def on_segment(point: Point, segment: Segment) -> bool:
    """Whether point lies on the closed segment, endpoints included."""
    start, end = segment
    if orientation(start, end, point) != COLLINEAR:
        return False
    return min(start[0], end[0]) <= point[0] <= max(start[0], end[0]) and (
        min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
    )


def segments_cross(first: Segment, second: Segment) -> bool:
    """A *proper* crossing: the two interiors meet at one point, transversally.

    Sharing an endpoint is not a crossing, and neither is an endpoint lying on the other
    segment. This is the distinction that decides SELF_INTERSECTION against
    RING_SELF_INTERSECTION, so it is deliberately strict.
    """
    a, b = first
    c, d = second
    first_side = orientation(a, b, c)
    second_side = orientation(a, b, d)
    third_side = orientation(c, d, a)
    fourth_side = orientation(c, d, b)
    if COLLINEAR in (first_side, second_side, third_side, fourth_side):
        return False
    return first_side != second_side and third_side != fourth_side


def collinear_overlap(first: Segment, second: Segment) -> bool:
    """Whether two collinear segments share more than a single point.

    A shared stretch of boundary, which JTS treats as an intersection however the
    segments are ordered. Touching at exactly one point is not an overlap.
    """
    a, b = first
    c, d = second
    if orientation(a, b, c) != COLLINEAR or orientation(a, b, d) != COLLINEAR:
        return False
    # Project onto the longer axis so a vertical segment is handled the same way.
    axis = 0 if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else 1
    first_low, first_high = sorted((a[axis], b[axis]))
    second_low, second_high = sorted((c[axis], d[axis]))
    low = max(first_low, second_low)
    high = min(first_high, second_high)
    return low < high


def segments_touch_or_overlap(first: Segment, second: Segment) -> bool:
    """Any shared point at all, crossing or not."""
    if segments_cross(first, second) or collinear_overlap(first, second):
        return True
    return any(
        on_segment(point, other)
        for point, other in (
            (first[0], second),
            (first[1], second),
            (second[0], first),
            (second[1], first),
        )
    )


def shared_points(first: Segment, second: Segment) -> set[Point]:
    """The endpoints the two segments have in common, for the touch graph."""
    return {point for point in first if point in second}


def remove_repeated(coordinates: list[Point]) -> list[Point]:
    """`CoordinateArrays.removeRepeatedPoints`: drop *consecutive* duplicates only.

    Measured, and not the same as counting distinct points: a ring tracing
    (0,0) (5,0) (0,0) (5,0) (0,0) keeps all five coordinates and is reported as a
    self-intersection, while (0,0) (1,1) (1,1) (0,0) collapses to three and is reported as
    having too few points. Counting distinct points would call both too few.
    """
    kept: list[Point] = []
    for point in coordinates:
        if not kept or point != kept[-1]:
            kept.append(point)
    return kept


def segments_of(ring: list[Point]) -> list[Segment]:
    return [(ring[index], ring[index + 1]) for index in range(len(ring) - 1)]


def point_in_ring(point: Point, ring: list[Point]) -> bool:
    """Ray casting with exact arithmetic. A point *on* the boundary is not inside."""
    for segment in segments_of(ring):
        if on_segment(point, segment):
            return False
    inside = False
    x, y = _exact(point[0]), _exact(point[1])
    for (x1, y1), (x2, y2) in segments_of(ring):
        first_y, second_y = _exact(y1), _exact(y2)
        if (first_y > y) == (second_y > y):
            continue
        first_x, second_x = _exact(x1), _exact(x2)
        crossing = first_x + (y - first_y) * (second_x - first_x) / (second_y - first_y)
        if crossing > x:
            inside = not inside
    return inside


def interior_point(ring: list[Point], other: list[Point]) -> Point | None:
    """A point of `ring` that is not on `other`'s boundary, for a containment test.

    Prefers a vertex, then a segment midpoint: a hole can touch the shell at every one of
    its vertices while still having an interior, and testing only vertices would then have
    nothing to work with.
    """
    other_segments = segments_of(other)
    for point in ring:
        if not any(on_segment(point, segment) for segment in other_segments):
            return point
    for (x1, y1), (x2, y2) in segments_of(ring):
        midpoint = ((x1 + x2) / 2, (y1 + y2) / 2)
        if not any(on_segment(midpoint, segment) for segment in other_segments):
            return midpoint
    return None
