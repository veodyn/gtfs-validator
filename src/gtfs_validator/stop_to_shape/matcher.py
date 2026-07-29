"""`StopToShapeMatcher`: assign each stop of a trip a place on the shape, or report why not.

Matching is not nearest-neighbour. Each stop has a *set* of candidate places on the shape, and the
assignment has to be monotonic: stop 5's place must lie no earlier along the shape than stop 4's.
Upstream finds the cheapest monotonic assignment with a forward pass that keeps, for each candidate
of the current stop, the best-scoring feasible assignment reaching it. Cost is the sum of the
stop-to-shape distances, so the cheapest assignment is the one that puts every stop as close to the
shape as monotonicity allows.

The three failure kinds map onto four notice codes because the too-far kind is reported under a
different code depending on which pass found it, and the two passes share one set of already
reported stop ids. That sharing is measured, not assumed: on a feed where both passes find the same
stop too far, only the geo code fires.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from gtfs_validator.stop_to_shape.matches import Match, MatchResult, Problem, ProblemType
from gtfs_validator.stop_to_shape.shape import ShapePoints
from gtfs_validator.stop_to_shape.stops import StopPoint, StopPoints

# StopToShapeMatcherSettings, at the defaults the validator constructs it with. No CLI flag reaches
# these; upstream exposes setters for its own tests only.
MAX_DISTANCE_FROM_STOP_TO_SHAPE_METERS = 100.0
LARGE_STATION_DISTANCE_MULTIPLIER = 4.0
POTENTIAL_MATCHES_PROBLEM_THRESHOLD = 20


@dataclass(frozen=True)
class Assignment:
    """A monotonic choice of one candidate per stop considered so far.

    `indices` holds the candidate index chosen for each stop, `score` the running sum of their
    distances to the shape, and `max_geo_distance` the last chosen candidate's distance *along* the
    shape, which is what the next stop's candidates are tested against.
    """

    indices: tuple[int, ...] = ()
    score: float = 0.0
    max_geo_distance: float = 0.0


def match_using_geo_distance(stop_points: StopPoints, shape_points: ShapePoints) -> MatchResult:
    """Match every stop by closest point, ignoring `shape_dist_traveled` entirely."""
    result = MatchResult()
    if stop_points.is_empty() or shape_points.is_empty():
        return result

    potential_matches: list[list[Match]] = []
    complete = True
    for point in stop_points.points:
        matches_for_stop = _potential_matches_using_geo_distance(
            shape_points, point, result.problems
        )
        potential_matches.append(matches_for_stop)
        # Every stop is attempted even after one fails, so a feed with two unmatchable stops draws
        # two too-far notices rather than one. `ok &= ...` rather than a break, in the Java.
        complete = complete and bool(matches_for_stop)
    if not complete:
        return result
    result.matches = _find_best_matches(stop_points, potential_matches, result.problems)
    return result


def match_using_user_distance(stop_points: StopPoints, shape_points: ShapePoints) -> MatchResult:
    """Match every stop by its `shape_dist_traveled`, falling back to geometry per stop.

    A stop with no user distance is matched by closest point instead, and if *that* finds nothing
    the whole pass abandons immediately, returning whatever problems it has already collected. The
    early return is upstream's, and it is the reason a single unmatchable stop can hide a later
    stop's user-distance problem.
    """
    result = MatchResult()
    if stop_points.is_empty() or shape_points.is_empty():
        return result

    potential_matches: list[list[Match]] = []
    search_from_index = 0
    for stop_point in stop_points.points:
        if not stop_point.has_user_distance():
            matches_for_stop = _potential_matches_using_geo_distance(
                shape_points, stop_point, result.problems
            )
            if not matches_for_stop:
                return result
        else:
            match = shape_points.match_from_user_dist(
                stop_point.user_distance, search_from_index, stop_point.location
            )
            matches_for_stop = [match]
            search_from_index = match.index
        potential_matches.append(matches_for_stop)

    result.matches = _find_best_matches(stop_points, potential_matches, result.problems)
    if result.matches and not _is_valid_match_from_user_distance(
        stop_points, result.matches, result.problems
    ):
        result.matches = []
    return result


def _potential_matches_using_geo_distance(
    shape_points: ShapePoints, stop_point: StopPoint, problems: list[Problem]
) -> list[Match]:
    """Candidates for one stop, and the two problems that finding them can turn up.

    Finding nothing within the threshold produces a too-far problem carrying the single closest
    point on the whole shape, so the notice can say how far away it actually is. Finding too many
    produces a too-many-matches problem but does **not** stop the matching: the candidates are
    returned and the assignment search still runs over them.
    """
    max_distance = MAX_DISTANCE_FROM_STOP_TO_SHAPE_METERS * (
        LARGE_STATION_DISTANCE_MULTIPLIER if stop_point.is_large_station else 1
    )
    matches_for_stop = shape_points.matches_from_location(stop_point.location, max_distance)
    if not matches_for_stop:
        match = shape_points.match_from_location(stop_point.location)
        if match.geo_distance_to_shape > max_distance:
            problems.append(
                Problem(ProblemType.STOP_TOO_FAR_FROM_SHAPE, stop_point.stop_time, match)
            )
        # Returned empty either way. A shape with no segments and no single point reaches here
        # with no best match at all, whose distance is infinity and so is not "too far".
        return matches_for_stop
    if len(matches_for_stop) > POTENTIAL_MATCHES_PROBLEM_THRESHOLD:
        problems.append(
            Problem(
                ProblemType.STOP_HAS_TOO_MANY_MATCHES,
                stop_point.stop_time,
                _closest(matches_for_stop),
                match_count=len(matches_for_stop),
            )
        )
    return matches_for_stop


def _find_best_matches(
    stop_points: StopPoints, potential_matches: list[list[Match]], problems: list[Problem]
) -> list[Match]:
    """The cheapest monotonic assignment, or an out-of-order problem and no matches.

    The forward pass keeps one assignment per candidate of the current stop rather than every
    assignment, which is what makes this linear in the candidate count instead of exponential: two
    assignments reaching the same candidate differ only in cost from here on, so the dearer one can
    never win.
    """
    partial_assignments = [Assignment()]
    matches: list[Match] = []
    for index in range(len(potential_matches)):
        next_assignments = _best_incremental_assignments(
            potential_matches[index], partial_assignments
        )
        if not next_assignments:
            problems.append(
                _out_of_order_problem(stop_points, potential_matches, index, partial_assignments)
            )
            # The matches collected so far are discarded, not returned: upstream returns the empty
            # list it has been holding, so a trip that fails at stop 7 reports no matches at all.
            return matches
        partial_assignments = next_assignments

    best = _lowest_scoring(partial_assignments).indices
    return [potential_matches[index][best[index]] for index in range(len(potential_matches))]


def _best_incremental_assignments(
    potential_matches: list[Match], previous_assignments: list[Assignment]
) -> list[Assignment]:
    """Extend the assignments by one stop, keeping the best predecessor for each candidate.

    A candidate is feasible after an assignment when the assignment's furthest point along the
    shape is no further than the candidate's, compared with `>` so an exact tie is allowed: two
    stops at the same place on the shape are ordered, not out of order.
    """
    next_assignments: list[Assignment] = []
    for index, match in enumerate(potential_matches):
        best_index = -1
        best_score = math.inf
        for previous_index, previous in enumerate(previous_assignments):
            if previous.max_geo_distance > match.geo_distance:
                continue
            if previous.score < best_score:
                best_index = previous_index
                best_score = previous.score
        if best_index != -1:
            partial = previous_assignments[best_index]
            next_assignments.append(
                Assignment(
                    indices=(*partial.indices, index),
                    score=partial.score + match.geo_distance_to_shape,
                    max_geo_distance=match.geo_distance,
                )
            )
    return next_assignments


def _out_of_order_problem(
    stop_points: StopPoints,
    potential_matches: list[list[Match]],
    index: int,
    previous_assignments: list[Assignment],
) -> Problem:
    """Describe the stop pair that made the assignment infeasible.

    The notice names the current stop's closest candidate and the previous stop's *assigned*
    candidate, which are chosen by different rules: the first by distance to the shape, the second
    by whichever the best-scoring surviving assignment picked. They are not interchangeable, and
    reporting the previous stop's closest candidate instead would name a place the matching never
    considered.
    """
    match = _closest(potential_matches[index])
    previous_assignment = _lowest_scoring(previous_assignments).indices
    previous_match = potential_matches[index - 1][previous_assignment[-1]]
    return Problem(
        ProblemType.STOPS_MATCH_OUT_OF_ORDER,
        stop_points.points[index].stop_time,
        match,
        previous_stop_time=stop_points.points[index - 1].stop_time,
        previous_match=previous_match,
    )


def _is_valid_match_from_user_distance(
    stop_points: StopPoints, matches: list[Match], problems: list[Problem]
) -> bool:
    """Report every user-distance match that lands too far from its stop.

    The threshold here is the plain one: the large-station multiplier is *not* applied, even for the
    rail terminus it was invented for. So a rail trip's first stop may be matched by geometry at up
    to 400 m and rejected by user distance at 101 m.
    """
    valid = True
    for stop_point, match in zip(stop_points.points, matches, strict=False):
        if match.geo_distance_to_shape > MAX_DISTANCE_FROM_STOP_TO_SHAPE_METERS:
            problems.append(
                Problem(ProblemType.STOP_TOO_FAR_FROM_SHAPE, stop_point.stop_time, match)
            )
            valid = False
    return valid


def _closest(matches: list[Match]) -> Match:
    """`Collections.min` by distance to the shape, which keeps the **first** of a tie."""
    best = matches[0]
    for match in matches[1:]:
        if match.geo_distance_to_shape < best.geo_distance_to_shape:
            best = match
    return best


def _lowest_scoring(assignments: list[Assignment]) -> Assignment:
    """`Collections.min` by score, keeping the first of a tie for the same reason."""
    best = assignments[0]
    for assignment in assignments[1:]:
        if assignment.score < best.score:
            best = assignment
    return best
