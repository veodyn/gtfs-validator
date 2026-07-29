"""Location-based matching against a shape: the two scans, and their pruned front doors.

Split from `shape.py` when the grid front doors pushed it past the file-size limit; the
split is by responsibility rather than by size alone. This module owns matching a point
against a shape's geometry, `shape.py` owns building the shape and matching by
`shape_dist_traveled`.

The `*_scan` functions are upstream's loops verbatim, and running them with no `indices`
is exactly what the validator did before the grid existed: they are the oracle the
equivalence tests hold the front doors to. The front doors ask `SegmentGrid` for a
conservative superset of candidate segments and run the same loops over only those, so
the floats a report carries never pass through the grid at all.
"""

from __future__ import annotations

import math

from gtfs_validator.s2earth import vector_distance_meters
from gtfs_validator.s2point import Point, closest_point, to_lat_lng_degrees
from gtfs_validator.stop_to_shape.matches import Match


def match_from_location(shape, location: Point) -> Match:
    """The single closest point on the shape, found without scanning every segment.

    The cell walk visits occupied cells nearest first and stops when the next cell's
    lower bound is *strictly* greater than the best exact distance seen, so a tying
    cell is still consumed. Selection is by `(distance, index)`, smallest first, which
    is exactly what the scan's ascending index order and strict `<` produce: the first
    segment index of an exact tie wins, and duplicated shape rows make exact ties
    real. A segment sits in every cell its box covers, so the walk sees the same index
    more than once and must evaluate it only the first time: the arithmetic per
    evaluated segment is the scan's own, once per segment, in a different order that
    the tie rule makes irrelevant.
    """
    grid = shape._segment_grid()
    if grid is None or not grid.enabled or len(shape.points) <= 1:
        return match_scan(shape, location)
    latitude, longitude = to_lat_lng_degrees(location)
    seen: set[int] = set()
    best_distance = math.inf
    best_index = -1
    best_closest: Point | None = None
    for indices, bound in grid.cells_by_bound(latitude, longitude):
        if bound > best_distance:
            break
        for index in indices:
            if index in seen:
                continue
            seen.add(index)
            left, right = shape.points[index], shape.points[index + 1]
            closest = closest_point(location, left.location, right.location)
            distance = vector_distance_meters(location, closest)
            if distance < best_distance or (distance == best_distance and index < best_index):
                best_distance = distance
                best_index = index
                best_closest = closest
    match = Match()
    if best_closest is not None:
        match.keep_best_match(best_closest, best_distance, best_index)
    if match.has_best_match():
        fill_location_match(shape, match)
    return match


def match_scan(shape, location: Point, indices: list[int] | None = None) -> Match:
    """The full closest-point scan, over all segments or a pruned set.

    Called only when the threshold search found nothing, to put a distance in the
    too-far notice. A one-point shape is handled first because the segment loop below
    cannot see it: with one point there are no segments at all, and without this the
    match would stay empty and the notice would report a zero-length shape as a perfect
    match.
    """
    match = Match()
    if len(shape.points) == 1:
        closest = shape.points[0].location
        match.keep_best_match(closest, vector_distance_meters(location, closest), 0)
    for index in range(len(shape.points) - 1) if indices is None else indices:
        left, right = shape.points[index], shape.points[index + 1]
        closest = closest_point(location, left.location, right.location)
        match.keep_best_match(closest, vector_distance_meters(location, closest), index)
    if match.has_best_match():
        fill_location_match(shape, match)
    return match


def matches_from_location(shape, location: Point, max_distance: float) -> list[Match]:
    """Every local minimum within `max_distance`, found without scanning every segment.

    The grid's candidates are a superset of the segments within threshold, so a skipped
    segment is provably beyond it, and beyond-threshold segments contribute nothing to
    the scan except banking the running local match, which the pruned scan reproduces at
    every index gap. A grid false positive takes the same `elif` the full scan took, so
    it needs no special case.
    """
    grid = shape._segment_grid()
    if grid is None or not grid.enabled:
        return matches_scan(shape, location, max_distance)
    latitude, longitude = to_lat_lng_degrees(location)
    candidates = grid.candidates(latitude, longitude, max_distance)
    return matches_scan(shape, location, max_distance, candidates)


def matches_scan(
    shape, location: Point, max_distance: float, indices: list[int] | None = None
) -> list[Match]:
    """Every local minimum of the distance from `location` to the shape, within `max_distance`.

    Not simply every close segment. A stop beside a long straight run of a shape is close to
    many consecutive segments and that is *one* candidate, not many; a stop that the shape
    passes twice is two. The loop therefore keeps one running best match and banks it only
    when the shape turns away, which it detects two ways: the current segment leaving the
    threshold, or the previous segment having been receding while this one closes again.

    This distinction is the whole content of `stop_has_too_many_matches_for_shape`. A first
    attempt at a probe for that code zig-zagged past a stop twenty-two times without ever
    leaving the threshold, and the jar reported nothing, because a zig-zag that stays close is
    one local minimum.
    """
    matches: list[Match] = []
    local_match = Match()
    distance_to_end_of_previous_segment = float("inf")
    previous_segment_getting_further_away = False
    previous_index: int | None = None

    for index in range(len(shape.points) - 1) if indices is None else indices:
        # An index gap means every skipped segment was beyond the threshold, and the
        # first of them is where the full scan banked the local match. The recede state
        # needs no reset: it is only ever read when the local match has a best, which
        # the bank just cleared.
        if (
            previous_index is not None
            and index > previous_index + 1
            and local_match.has_best_match()
        ):
            matches.append(local_match.copy())
            local_match.clear_best_match()
        previous_index = index

        left, right = shape.points[index], shape.points[index + 1]
        closest = closest_point(location, left.location, right.location)
        geo_distance_to_shape = vector_distance_meters(location, closest)

        if geo_distance_to_shape <= max_distance:
            if (
                previous_segment_getting_further_away
                and geo_distance_to_shape < distance_to_end_of_previous_segment
                and local_match.has_best_match()
            ):
                matches.append(local_match.copy())
                local_match.clear_best_match()
            local_match.keep_best_match(closest, geo_distance_to_shape, index)
        elif local_match.has_best_match():
            matches.append(local_match.copy())
            local_match.clear_best_match()

        # Measured to the segment's far *vertex*, not to its closest point: that is what makes
        # "receding" a statement about where the shape is heading rather than about how close
        # it came.
        distance_to_end_of_previous_segment = vector_distance_meters(location, right.location)
        previous_segment_getting_further_away = (
            distance_to_end_of_previous_segment > geo_distance_to_shape
        )

    if local_match.has_best_match():
        matches.append(local_match)

    for match in matches:
        fill_location_match(shape, match)
    return matches


def fill_location_match(shape, match: Match) -> None:
    """`fillLocationMatch`: the distance along the shape to a closest-point match.

    The vertex's own running distance plus the hop from it to the match. `user_distance` is
    reset to zero rather than interpolated, so a closest-point match carries no user distance
    even on a shape that has them.
    """
    shape_point = shape.points[match.index]
    match.geo_distance = shape_point.geo_distance + vector_distance_meters(
        match.location, shape_point.location
    )
    match.user_distance = 0.0
