"""`Geometry.overlaps` for two polygons, which is what decides one notice.

`OverlappingPickupDropOffZoneValidator` asks `GtfsGeoJsonFeature.geometryOverlaps`, which is
JTS's `overlaps`. That is the DE-9IM predicate and not the plain-English word: two areas overlap
when their interiors share area **and neither contains the other**. So a zone inside another
zone does not overlap it, a zone sharing only an edge does not, and two identical zones do not.
All three measured against the jar on a feed built for them.

Spelled out, the predicate is three conditions at once:

    A overlaps B  <=>  their interiors share area
                       and A has interior outside B
                       and B has interior outside A.

An earlier version of this file decided all three from A's *boundary*, on the argument that a
boundary staying inside B's closure means A is contained in B. That argument is false, and a
review produced the counterexample: two polygons with the **same shell** and holes in different
corners. A's boundary is its shell, which lies on B's boundary, plus its hole, which lies inside
B; nowhere does it leave B's closure. Yet A has interior outside B, in the region B punches out
as its own hole, and JTS answers TRUE. A boundary walk cannot see area reached through the other
polygon's hole, so the boundary is the wrong thing to look at.

What is here instead is a vertical strip sweep, which looks at the faces. Cut the plane at every
x where anything happens: every vertex and every edge crossing. Between two consecutive such x
values nothing changes topologically, so each face of the arrangement spans the whole strip and a
single vertical line through the strip's middle meets every one of them. On that line each
polygon is a set of y intervals, and the three conditions become interval arithmetic: the
intervals overlap somewhere, A's have a piece outside B's, B's have a piece outside A's. Every
face is sampled exactly once, which is what makes this complete rather than merely plausible.

Everything is computed in `Fraction`, as the rest of this package is. A feed's coordinates are
floats and a float is a rational, so the cut positions and the sampling lines are exact: no
epsilon decides whether a zone boundary is inside its neighbour.

Only `Polygon` is handled, and that is not a simplification. Upstream's coordinate walk indexes
to a fixed depth and throws on anything deeper, so a MultiPolygon is dropped before the geometry
type dispatch and never becomes a feature. See `geojson.features` and divergence 6.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import pairwise

Exact = tuple[Fraction, Fraction]
Ring = list[Exact]
# A polygon is its shell followed by its holes, which is GeoJSON's own order.
Polygon = list[Ring]

OUTSIDE = 0
INSIDE = 1
BOUNDARY = 2


def to_exact(rings) -> Polygon:
    """A GeoJSON coordinate list as exact rings.

    Two coercions, both upstream's rather than convenience. Every ordinate past the first two is
    ignored, because a GeoJSON position may carry an altitude and upstream's coordinate walk reads
    index 0 and 1 and nothing else; unpacking the pair instead raised on any 3D feature, which
    for a *file rule* means the whole rule's notices are discarded. And a value goes through
    `float` first, matching `getAsDouble`, so the string "2.1" and the number 2.1 become the same
    coordinate: `Fraction("2.1")` is exactly 21/10 and `Fraction(2.1)` is the double next to it,
    and two zones written the two ways would otherwise differ by that much.

    The closing point is kept. A GeoJSON ring repeats its first position as its last, and the
    edge walk below relies on that to close the ring.
    """
    return [
        [(Fraction(float(position[0])), Fraction(float(position[1]))) for position in ring]
        for ring in rings
    ]


def polygons_overlap(first: Polygon, second: Polygon) -> bool:
    """JTS `overlaps` for two polygons: interiors meet, and each has area the other lacks."""
    if not first or not second or not first[0] or not second[0]:
        return False
    edges = list(_edges(first)) + list(_edges(second))
    shared = first_only = second_only = False
    for line in _sampling_lines(edges):
        left = _inside_intervals(first, line)
        right = _inside_intervals(second, line)
        if not shared:
            shared = _intersects(left, right)
        if not first_only:
            first_only = _has_remainder(left, right)
        if not second_only:
            second_only = _has_remainder(right, left)
        if shared and first_only and second_only:
            return True
    return False


def _sampling_lines(edges: list[tuple[Exact, Exact]]) -> list[Fraction]:
    """One x per strip: the midpoint between consecutive x values where anything happens.

    "Anything" is a vertex or a crossing. Between two consecutive such values no edge starts,
    ends or meets another, so the vertical order of the edges is fixed across the strip and every
    face of the arrangement spans it. That is what lets one line per strip stand for the strip,
    and why the midpoint is safe: it is never a vertex's x, so no vertical edge lies on it.
    """
    cuts = {x for edge in edges for x, _ in edge}
    for index, edge in enumerate(edges):
        for other in edges[index + 1 :]:
            cuts.update(_crossing_x(edge, other))
    return [(low + high) / 2 for low, high in pairwise(sorted(cuts))]


def _crossing_x(edge: tuple[Exact, Exact], other: tuple[Exact, Exact]) -> list[Fraction]:
    """The x of any point the two segments share, for a collinear pair their endpoints' x."""
    (ax, ay), (bx, by) = edge
    (cx, cy), (dx, dy) = other
    direction = (bx - ax, by - ay)
    span = (dx - cx, dy - cy)
    denominator = _cross(direction, span)
    offset = (cx - ax, cy - ay)
    if denominator == 0:
        if _cross(offset, direction) != 0:
            return []
        return [cx, dx]
    along = _cross(offset, span) / denominator
    across = _cross(offset, direction) / denominator
    if 0 <= along <= 1 and 0 <= across <= 1:
        return [ax + direction[0] * along]
    return []


def _inside_intervals(polygon: Polygon, x: Fraction) -> list[tuple[Fraction, Fraction]]:
    """Where the vertical line at `x` is inside the polygon, as disjoint ascending intervals.

    Even-odd over every ring at once, which is exactly "the shell minus its holes" as long as the
    holes lie inside the shell: crossing into a hole flips the count back to outside. The line
    never touches a vertex, so no crossing has to be counted once or twice by convention.
    """
    crossings = []
    for (x1, y1), (x2, y2) in _edges(polygon):
        if (x1 < x) == (x2 < x):
            # Both endpoints on one side, or the edge is vertical at another x.
            continue
        crossings.append(y1 + (x - x1) * (y2 - y1) / (x2 - x1))
    crossings.sort()
    return list(zip(crossings[::2], crossings[1::2], strict=False))


def _intersects(
    left: list[tuple[Fraction, Fraction]], right: list[tuple[Fraction, Fraction]]
) -> bool:
    """Whether any pair of intervals shares more than a point."""
    return any(
        max(low, other_low) < min(high, other_high)
        for low, high in left
        for other_low, other_high in right
    )


def _has_remainder(
    left: list[tuple[Fraction, Fraction]], right: list[tuple[Fraction, Fraction]]
) -> bool:
    """Whether `left` has a stretch of positive length that `right` does not cover.

    The stretch has to be positive: two polygons meeting along an edge leave a remainder of zero
    length, which is a shared boundary rather than area only one of them has.
    """
    for low, high in left:
        position = low
        for other_low, other_high in right:
            if other_high <= position or other_low >= high:
                continue
            if other_low > position:
                return True
            position = max(position, other_high)
            if position >= high:
                break
        if position < high:
            return True
    return False


def _edges(polygon: Polygon):
    """Every ring's segments, holes included: a hole's boundary is part of the polygon's."""
    for ring in polygon:
        for index in range(len(ring) - 1):
            if ring[index] != ring[index + 1]:
                yield ring[index], ring[index + 1]


def _cut_parameters(start: Exact, end: Exact, others) -> list[Fraction]:
    """0 and 1 plus every parameter along this edge where B's boundary meets it.

    Sorted and deduplicated, so consecutive pairs are the pieces to sample. A collinear overlap
    contributes both of its endpoints, since the piece between them lies *on* B's boundary and
    has to be separated from the pieces either side of it.
    """
    cuts = {Fraction(0), Fraction(1)}
    for other_start, other_end in others:
        cuts.update(_meeting_parameters(start, end, other_start, other_end))
    return sorted(cuts)


def _meeting_parameters(
    start: Exact, end: Exact, other_start: Exact, other_end: Exact
) -> list[Fraction]:
    """The parameters in [0, 1] along start->end at which it meets other_start->other_end."""
    direction = (end[0] - start[0], end[1] - start[1])
    other = (other_end[0] - other_start[0], other_end[1] - other_start[1])
    denominator = _cross(direction, other)
    offset = (other_start[0] - start[0], other_start[1] - start[1])
    if denominator != 0:
        parameter = _cross(offset, other) / denominator
        along_other = _cross(offset, direction) / denominator
        if 0 <= parameter <= 1 and 0 <= along_other <= 1:
            return [parameter]
        return []
    # Parallel. Only a collinear pair can meet, and then it meets along a stretch.
    if _cross(offset, direction) != 0:
        return []
    squared_length = direction[0] * direction[0] + direction[1] * direction[1]
    if squared_length == 0:
        return []
    found = []
    for point in (other_start, other_end):
        parameter = (
            (point[0] - start[0]) * direction[0] + (point[1] - start[1]) * direction[1]
        ) / squared_length
        if 0 <= parameter <= 1:
            found.append(parameter)
    return found


def classify(point: Exact, polygon: Polygon) -> int:
    """Whether the point is inside the polygon, outside it, or on its boundary.

    A hole's inside is the polygon's outside, and a hole's edge is the polygon's boundary. Both
    follow from a polygon being its shell minus its holes, and the second is what keeps two
    zones that share a hole edge from reading as overlapping.
    """
    for edge in _edges(polygon):
        if _on_edge(point, edge):
            return BOUNDARY
    if not _in_ring(point, polygon[0]):
        return OUTSIDE
    for hole in polygon[1:]:
        if _in_ring(point, hole):
            return OUTSIDE
    return INSIDE


def _on_edge(point: Exact, edge: tuple[Exact, Exact]) -> bool:
    start, end = edge
    if _cross((end[0] - start[0], end[1] - start[1]), (point[0] - start[0], point[1] - start[1])):
        return False
    return min(start[0], end[0]) <= point[0] <= max(start[0], end[0]) and (
        min(start[1], end[1]) <= point[1] <= max(start[1], end[1])
    )


def _in_ring(point: Exact, ring: Ring) -> bool:
    """Ray casting, exactly. The caller has already ruled out a point on the boundary."""
    x, y = point
    inside = False
    for index in range(len(ring) - 1):
        (x1, y1), (x2, y2) = ring[index], ring[index + 1]
        if (y1 > y) == (y2 > y):
            continue
        crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        if crossing > x:
            inside = not inside
    return inside


def _cross(first: tuple[Fraction, Fraction], second: tuple[Fraction, Fraction]) -> Fraction:
    return first[0] * second[1] - first[1] * second[0]
