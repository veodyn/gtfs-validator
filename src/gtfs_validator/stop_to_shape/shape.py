"""`ShapePoints`: a shape as a sequence of unit vectors carrying two running distances.

Each point holds a *geo distance*, the great-circle length of the shape up to it, and a *user
distance*, the `shape_dist_traveled` the file gave. The two are independent parameterizations of
the same polyline and upstream matches stops against both, reporting a separate notice code for
each, so neither can be derived from the other here.

Two constructions look like arithmetic and are decisions:

- The geo distance clamps each hop at zero (`Math.max(0.0, ...)`). A negative hop is impossible
  for a great-circle distance, so this guards against a NaN or a signed zero rather than against
  real geometry.
- The user distance is a running **maximum**, not the row's value. A shape whose
  `shape_dist_traveled` decreases therefore carries the earlier, larger value forward, which is
  what makes the user-distance search monotonic even on a feed that is not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from gtfs_validator.s2earth import distance_meters, vector_distance_meters
from gtfs_validator.s2point import (
    Point,
    approx_equals,
    interpolate,
    to_point,
)
from gtfs_validator.stop_to_shape import location_match
from gtfs_validator.stop_to_shape.matches import Match
from gtfs_validator.stop_to_shape.segment_grid import SegmentGrid

# MathUtil.DOUBLE_STD_ERR, the fraction and the margin `nearByFractionOrMargin` uses for both.
DOUBLE_STD_ERR = 1e-9 * 32


@dataclass(frozen=True)
class ShapePoint:
    geo_distance: float
    user_distance: float
    location: Point

    def has_user_distance(self) -> bool:
        """Strictly positive, so a shape whose distances are all zero counts as having none."""
        return self.user_distance > 0.0


class ShapePoints:
    """One shape's points, in `shape_pt_sequence` order."""

    def __init__(
        self, points: list[ShapePoint], latlons: list[tuple[float, float]] | None = None
    ) -> None:
        self.points = points
        # The raw coordinates, kept only to feed the segment grid: the unit vectors
        # cannot be turned back into degrees without rounding, and the grid's bounds
        # want the numbers the feed gave. A ShapePoints built without them, as the
        # matcher unit tests do, simply never builds a grid and scans as before.
        self._latlons = latlons
        self._grid: SegmentGrid | None = None

    @classmethod
    def from_rows(cls, rows: list[dict]) -> ShapePoints:
        """Build from `shapes.txt` rows already sorted by sequence.

        A missing `shape_dist_traveled` reads as 0.0, which is what `GtfsShape.shapeDistTraveled()`
        returns for an unset double. That is not the same as skipping the row: the running maximum
        keeps whatever came before, and the point still contributes its geometry.

        **The hop distance is the haversine, not the vector form.** Upstream passes
        `shapePtLatLon()` here, which is an `S2LatLng`, so this line reaches the other
        `getDistanceMeters` overload from the one every other distance in this file uses. The two
        are different formulas rather than one wrapping the other, and they disagree in the last
        digits: this value ends up in `geoDistance`, which orders the assignment search, so using
        the vector form would be a silent difference in which matches are feasible.
        """
        points: list[ShapePoint] = []
        geo_distance = 0.0
        user_distance = 0.0
        previous: tuple[float, float] | None = None
        for row in rows:
            latitude, longitude = row["shape_pt_lat"], row["shape_pt_lon"]
            if previous is not None:
                geo_distance += _java_max(0.0, distance_meters(*previous, latitude, longitude))
            distance = row.get("shape_dist_traveled")
            user_distance = _java_max(user_distance, 0.0 if distance is None else distance)
            points.append(ShapePoint(geo_distance, user_distance, to_point(latitude, longitude)))
            previous = (latitude, longitude)
        return cls(points, [(row["shape_pt_lat"], row["shape_pt_lon"]) for row in rows])

    def is_empty(self) -> bool:
        return not self.points

    def has_user_distance(self) -> bool:
        """Decided by the **last** point alone, as `Iterables.getLast` does.

        So a shape that gives distances for its first half and nothing after counts as having
        none, because the running maximum makes the last point's value positive only if some
        earlier row set it. That is upstream's test, not a simplification of it.
        """
        return bool(self.points) and self.points[-1].has_user_distance()

    def _segment_grid(self) -> SegmentGrid | None:
        """The grid, built once on first use, or None for a shape built without coordinates."""
        if self._grid is None and self._latlons is not None and len(self._latlons) >= 2:
            self._grid = SegmentGrid(self._latlons)
        return self._grid

    def match_from_location(self, location: Point) -> Match:
        """The single closest point on the shape, however far away it is.

        Delegated to `location_match`, which prunes the scan through the segment grid
        and holds the docstrings for why the pruned result is exact.
        """
        return location_match.match_from_location(self, location)

    def _match_from_location_scan(self, location: Point, indices: list[int] | None = None) -> Match:
        """The unpruned loop, kept callable as the oracle the equivalence tests use."""
        return location_match.match_scan(self, location, indices)

    def matches_from_location(self, location: Point, max_distance: float) -> list[Match]:
        """Every local minimum within `max_distance`. Delegated like `match_from_location`."""
        return location_match.matches_from_location(self, location, max_distance)

    def _matches_from_location_scan(
        self, location: Point, max_distance: float, indices: list[int] | None = None
    ) -> list[Match]:
        """The unpruned loop, kept callable as the oracle the equivalence tests use."""
        return location_match.matches_scan(self, location, max_distance, indices)

    def match_from_user_dist(
        self, user_dist: float, start_index: int, stop_location: Point
    ) -> Match:
        """The point on the shape whose `shape_dist_traveled` is `user_dist`.

        The search starts at `start_index` rather than at the beginning, so a stop's match can
        never precede the previous stop's. That is why the user-distance pass reports out-of-order
        matches so rarely: the monotonicity is built into the search instead of being checked.
        """
        return self._interpolate(
            self._vertex_dist_from_user_dist(user_dist, start_index), stop_location
        )

    def _vertex_dist_from_user_dist(self, user_dist: float, start_index: int) -> tuple[int, float]:
        """The vertex index and the fraction past it, for a given user distance.

        Three cases return a fraction of zero rather than interpolating: the distance falling
        before the shape starts, after it ends, or between two vertices whose distances are equal
        to within `MathUtil.nearByFractionOrMargin`. The third exists because the fraction is a
        ratio of two nearly equal numbers, and upstream's comment says so.
        """
        previous_index = start_index
        next_index = start_index
        while next_index < len(self.points) and user_dist >= self.points[next_index].user_distance:
            previous_index = next_index
            next_index += 1
        if next_index <= 0 or previous_index + 1 >= len(self.points):
            return (previous_index, 0.0)
        previous_distance = self.points[previous_index].user_distance
        next_distance = self.points[next_index].user_distance
        if _near_by_fraction_or_margin(previous_distance, next_distance):
            return (previous_index, 0.0)
        return (
            previous_index,
            (user_dist - previous_distance) / (next_distance - previous_distance),
        )

    def _interpolate(self, vertex_dist: tuple[int, float], stop_location: Point) -> Match:
        """Build a match at a fractional position along one segment.

        `geo_distance` is interpolated linearly between the two vertices rather than measured,
        which is upstream's choice and is not the same number: the chord it walks along is the
        shape's, so the two agree only when the segment is straight in the parameterization. The
        `approx_equals` guard is what keeps a repeated shape row from interpolating to NaN.
        """
        previous_index, fraction = vertex_dist
        previous_point = self.points[previous_index]
        next_point = (
            previous_point
            if previous_index + 1 == len(self.points)
            else self.points[previous_index + 1]
        )
        location = (
            previous_point.location
            if approx_equals(previous_point.location, next_point.location)
            else interpolate(fraction, previous_point.location, next_point.location)
        )
        return Match(
            index=previous_index,
            user_distance=previous_point.user_distance
            + fraction * (next_point.user_distance - previous_point.user_distance),
            geo_distance=previous_point.geo_distance
            + fraction * (next_point.geo_distance - previous_point.geo_distance),
            geo_distance_to_shape=vector_distance_meters(stop_location, location),
            location=location,
        )

    def _fill_location_match(self, match: Match) -> None:
        """`fillLocationMatch`: the distance along the shape to a closest-point match.

        The vertex's own running distance plus the hop from it to the match. `user_distance` is
        reset to zero rather than interpolated, so a closest-point match carries no user distance
        even on a shape that has them.
        """
        shape_point = self.points[match.index]
        match.geo_distance = shape_point.geo_distance + vector_distance_meters(
            match.location, shape_point.location
        )
        match.user_distance = 0.0


def _java_max(first: float, second: float) -> float:
    """`Math.max`, which returns NaN if either argument is NaN.

    Python's `max` does not: it keeps its running value unless the next one compares greater, and
    every comparison against NaN is false, so `max(0.0, nan)` is 0.0 while `max(nan, 0.0)` is NaN.
    The argument order therefore decides whether a NaN survives, which is not a difference a reader
    of the Java would expect to have to think about.

    It changes behaviour rather than a digit. Accumulating `[0, NaN, 1000]` gives `0, NaN, NaN` in
    Java and `0, 0, 1000` with Python's `max`, so the shape's last point has a positive user
    distance here and a NaN one there: `has_user_distance` is then True for us and False for
    upstream, and the whole user-distance pass runs on one side only. A NaN
    `shape_dist_traveled` is reachable, which is what known-divergences entry 12's
    `trip_shape_nan_max` note is about.

    `gtfs_validator.s2earth` guards the mirror-image case for `Math.min` inline, with its own comment,
    for the same reason. `s2point._java_divide` is the third of these.
    """
    if first != first or second != second:
        return math.nan
    return first if first > second else second


def _near_by_fraction_or_margin(first: float, second: float) -> bool:
    """`MathUtil.nearByFractionOrMargin`, which is a relative *or* absolute test.

    Infinities are never near anything, including themselves, which is upstream's first line and
    not an accident of the comparison below it.
    """
    if first in (float("inf"), float("-inf")) or second in (float("inf"), float("-inf")):
        return False
    relative_margin = DOUBLE_STD_ERR * max(abs(first), abs(second))
    return abs(first - second) <= max(DOUBLE_STD_ERR, relative_margin)
