"""`IsValidOp` for the polygons locations.geojson can carry, in the jar's check order.

The order is not cosmetic: several errors apply to one shape and only the first is
reported. Every line of the order below was measured with
`tools/diff_geometry_against_jts.py`, on shapes built to make two errors compete:

| Shape | Errors that apply | Reported |
|---|---|---|
| NaN vertex on a bow-tie ring | coordinate, self-intersection | Invalid Coordinate |
| collapsed ring plus a hole outside the shell | too few points, hole outside | Too few distinct points |
| bow-tie ring plus a hole outside the shell | self-intersection, hole outside | Self-intersection |
| hole outside the shell, in the first of two members | hole outside, nested shells | Hole lies outside shell |

The last row is why a multi-polygon validates each member fully before any collection
check: upstream builds the members first and returns on the first invalid one.

Only errors 2, 3, 4, 5, 6, 7, 9 and 10 are reachable this way. `Repeated Point`,
`Duplicate Rings` and `Ring is not closed` are not: repeated points are legal, duplicate
rings are reported as a self-intersection, and an unclosed ring is refused by
`GeometryFactory` before `IsValidOp` ever sees it, so its message comes from the
exception instead. All three were checked against the jar rather than assumed.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from importlib.resources import files

from gtfs_validator.geometry.predicates import (
    Point,
    collinear_overlap,
    interior_point,
    on_segment,
    point_in_ring,
    remove_repeated,
    segments_cross,
    segments_of,
    segments_touch_or_overlap,
    shared_points,
)

Ring = list[Point]
Polygon = list[Ring]

INVALID_COORDINATE = "INVALID_COORDINATE"
TOO_FEW_POINTS = "TOO_FEW_POINTS"
SELF_INTERSECTION = "SELF_INTERSECTION"
RING_SELF_INTERSECTION = "RING_SELF_INTERSECTION"
HOLE_OUTSIDE_SHELL = "HOLE_OUTSIDE_SHELL"
NESTED_HOLES = "NESTED_HOLES"
NESTED_SHELLS = "NESTED_SHELLS"
DISCONNECTED_INTERIOR = "DISCONNECTED_INTERIOR"

# LinearRing needs three coordinates and LineString two, so a one-point ring is refused by
# LineString's check before LinearRing's runs and carries LineString's wording. Both
# bounds and both spellings are in data/jts_messages.json, measured.
_MIN_LINESTRING_POINTS = 2
_MIN_LINEARRING_POINTS = 3
_MIN_VALID_RING_POINTS = 4


def _closed(ring: Ring) -> bool:
    """Coordinate.equals compares doubles with ==, so a NaN endpoint closes nothing.

    Python tuple equality would call two NaN-bearing endpoints equal, because it compares
    by identity first and the JSON decoder reuses one NaN object. That made a ring the jar
    refuses for not closing look closed, and it was then reported as an invalid coordinate
    instead. Measured on `NaN,0 1,0 1,1 NaN,0`.
    """
    first, last = ring[0], ring[-1]
    if any(math.isnan(value) for value in (*first, *last)):
        return False
    return first == last


def construction_message(ring: Ring) -> str | None:
    """The IllegalArgumentException `GeometryFactory` would raise for this ring.

    An empty ring is accepted, so this returns None for it: upstream builds an empty
    geometry and finds it valid.
    """
    count = len(ring)
    if count == 0:
        return None
    if count < _MIN_LINESTRING_POINTS:
        return (
            f"Invalid number of points in LineString (found {count} - must be 0 or >= "
            f"{_MIN_LINESTRING_POINTS})"
        )
    if count < _MIN_LINEARRING_POINTS:
        return (
            f"Invalid number of points in LinearRing (found {count} - must be 0 or >= "
            f"{_MIN_LINEARRING_POINTS})"
        )
    if not _closed(ring):
        return _construction_errors()["unclosed_ring"]
    return None


def polygon_construction_message(rings: Polygon) -> str | None:
    """What `createPolygon` refuses, for the whole ring set rather than one ring.

    An empty shell is fine on its own and so is an empty hole, but an empty shell beside a
    non-empty hole has its own wording. Measured; it is the only construction message that
    is not about a single ring.
    """
    for ring in rings:
        message = construction_message(ring)
        if message is not None:
            return message
    if rings and not rings[0] and any(rings[1:]):
        return _construction_errors()["shell_empty_holes_not"]
    return None


@lru_cache(maxsize=1)
def _construction_errors() -> dict[str, str]:
    raw = json.loads(files("gtfs_validator.data").joinpath("jts_messages.json").read_text())
    return raw["construction_errors"]


def _is_finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _coordinates_valid(rings: list[Ring]) -> bool:
    return all(_is_finite(x) and _is_finite(y) for ring in rings for x, y in ring)


def _self_intersection(ring: Ring) -> str | None:
    """A ring against itself: a crossing is one error, a mere touch another.

    Repeated points are removed first, because a zero-length segment touches its
    neighbour at a point and counting that reported nine valid rings in the random corpus.
    Adjacent segments are then examined only for collinear overlap: sharing the vertex
    between them is what makes them adjacent, but doubling back along each other is not.

    Which of the two errors the jar reports for a *touch* is not fully reproduced here.
    The boundary is measured but not derivable, so this
    reports the crossing case exactly and takes the touch case as a documented risk.
    """
    segments = segments_of(remove_repeated(ring))
    touch = False
    for first in range(len(segments)):
        for second in range(first + 1, len(segments)):
            adjacent = second == first + 1 or (first == 0 and second == len(segments) - 1)
            if adjacent:
                if collinear_overlap(segments[first], segments[second]):
                    touch = True
                continue
            if segments_cross(segments[first], segments[second]):
                return SELF_INTERSECTION
            if segments_touch_or_overlap(segments[first], segments[second]):
                touch = True
    return RING_SELF_INTERSECTION if touch else None


def _rings_intersect(first: Ring, second: Ring) -> bool:
    """Whether two distinct rings share more than isolated points.

    A crossing or a shared stretch of boundary makes the polygon self-intersecting.
    Meeting at single points does not, and is what the interior-connectivity check later
    counts.
    """
    for left in segments_of(first):
        for right in segments_of(second):
            if segments_cross(left, right) or collinear_overlap(left, right):
                return True
    return False


def _touch_points(first: Ring, second: Ring) -> set[Point]:
    """Every isolated point at which two rings meet, for the touch graph."""
    points: set[Point] = set()
    for left in segments_of(first):
        for right in segments_of(second):
            if not segments_touch_or_overlap(left, right):
                continue
            points |= shared_points(left, right)
            points |= {point for point in left if on_segment(point, right)}
            points |= {point for point in right if on_segment(point, left)}
    return points


def _interior_disconnected(rings: list[Ring]) -> bool:
    """`ConnectedInteriorTester`: a loop through *distinct* touch points pinches the interior.

    Nodes are the rings and every place two rings meet is an edge, but the edges have to be
    grouped by location, not counted. Three rings meeting at one point is a star: it joins
    them without enclosing anything, and the jar calls it valid. A hole touching the shell
    at two different points is a loop, and the area between them is cut off.

    Counting edges instead reported two holes that share a single point with the shell as a
    disconnected interior, where the jar reports nothing: found by a review that ran 74,862
    shapes past the corpus this was built against.
    """
    incident: dict[Point, set[int]] = {}
    for first in range(len(rings)):
        for second in range(first + 1, len(rings)):
            for point in _touch_points(rings[first], rings[second]):
                incident.setdefault(point, set()).update((first, second))

    parent = list(range(len(rings)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for members in incident.values():
        roots = {find(member) for member in members}
        if len(roots) < len(members):
            # Two rings meeting here were already joined elsewhere: that closes a loop.
            return True
        target = roots.pop()
        for root in roots:
            parent[root] = target
    return False


def _too_few_points(rings: Polygon) -> str | None:
    """Every non-empty ring needs four coordinates once consecutive duplicates are gone.

    Empty is exempt: `GeometryFactory` builds an empty LinearRing and `IsValidOp` finds a
    polygon with an empty hole valid. Counting it as too few reported the one verdict
    mismatch left in the corpus after the review's fixes.
    """
    for ring in rings:
        if ring and len(remove_repeated(ring)) < _MIN_VALID_RING_POINTS:
            return TOO_FEW_POINTS
    return None


def _shell_self_intersection(rings: Polygon) -> str | None:
    """The shell against itself, ahead of everything about the holes.

    A figure-eight shell beside a detached hole is reported as a ring self-intersection, not
    as a hole outside the shell: measured, and an earlier ordering here got it backwards.
    """
    return _self_intersection(rings[0])


def _hole_self_intersections(rings: Polygon) -> str | None:
    """The holes against themselves, *after* the containment checks.

    The shell's own error outranks the hole checks and a hole's own error does not, which
    reads as inconsistent until you see it measured: a polygon whose hole both self-crosses
    and lies outside the shell is reported as the hole lying outside. Four random shapes
    disagreed on exactly this before the two were split apart.
    """
    for ring in rings[1:]:
        error = _self_intersection(ring)
        if error is not None:
            return error
    return None


def _cross_ring_intersections(rings: Polygon) -> str | None:
    """Two different rings sharing more than isolated points, once every ring is simple."""
    for first in range(len(rings)):
        for second in range(first + 1, len(rings)):
            if _rings_intersect(rings[first], rings[second]):
                return SELF_INTERSECTION
    return None


def _holes_outside_shell(rings: Polygon) -> str | None:
    shell, holes = rings[0], rings[1:]
    for hole in holes:
        probe = interior_point(hole, shell)
        if probe is not None and not point_in_ring(probe, shell):
            return HOLE_OUTSIDE_SHELL
    return None


def _holes_nested(rings: Polygon) -> str | None:
    holes = rings[1:]
    for first, hole in enumerate(holes):
        for second, other in enumerate(holes):
            if first == second:
                continue
            probe = interior_point(hole, other)
            if probe is not None and point_in_ring(probe, other):
                return NESTED_HOLES
    return None


def _disconnected(rings: Polygon) -> str | None:
    return DISCONNECTED_INTERIOR if _interior_disconnected(rings) else None


# The order the jar reports in. Each entry returns an error name or None; the first name
# wins, which is the whole point of keeping them in a list rather than inlining them.
_POLYGON_CHECKS = (
    _too_few_points,
    _shell_self_intersection,
    _cross_ring_intersections,
    _holes_outside_shell,
    _holes_nested,
    _hole_self_intersections,
    _disconnected,
)


def validate_polygon(rings: Polygon) -> str | None:
    """The error name the jar would report for one polygon, or None if it is valid."""
    if not rings or not rings[0]:
        return None
    # Ahead of the list because it outranks everything, including a shape that would
    # otherwise be refused at construction: a NaN vertex is reported as an invalid
    # coordinate rather than as an unclosed ring when the ring does close elsewhere.
    if not _coordinates_valid(rings):
        return INVALID_COORDINATE
    for check in _POLYGON_CHECKS:
        error = check(rings)
        if error is not None:
            return error
    return None


def validate_multipolygon(polygons: list[Polygon]) -> str | None:
    """Every member first, then the collection, matching how upstream builds them."""
    for polygon in polygons:
        error = validate_polygon(polygon)
        if error is not None:
            return error
    for first in range(len(polygons)):
        for second in range(first + 1, len(polygons)):
            if _members_intersect(polygons[first], polygons[second]):
                return SELF_INTERSECTION
    for first, polygon in enumerate(polygons):
        for second, other in enumerate(polygons):
            if first == second or not polygon or not other:
                continue
            if _shell_nested_in(polygon, other):
                return NESTED_SHELLS
    return None


def _members_intersect(first: Polygon, second: Polygon) -> bool:
    return any(_rings_intersect(left, right) for left in first for right in second)


def _shell_nested_in(polygon: Polygon, other: Polygon) -> bool:
    """Whether one member's shell sits inside another's, and not inside one of its holes.

    A shell inside another member's *hole* is valid: the hole is not part of that member,
    so the two interiors stay disjoint. Measured, and the reason this is not a plain
    point-in-shell test.
    """
    probe = interior_point(polygon[0], other[0])
    if probe is None or not point_in_ring(probe, other[0]):
        return False
    return not any(point_in_ring(probe, hole) for hole in other[1:])
