"""ShapeIncreasingDistanceValidator: one distance claimed at two places barely apart.

The warning half of the differing-coordinates split: the same condition as
`equal_shape_distance_diff_coordinates`, for pairs closer than 1.11 m. Two coordinates that differ
only in their last decimal place are a rounding artefact rather than a contradiction, which is why
this is a warning.

The lower bound is strict. Upstream's branch is `> 0`, and it is not dead code guarding against a
case the equality test already caught: the coordinate comparison is exact, so two points can differ
in `shape_pt_lat` and still measure 0 m apart once the haversine underflows. Such a pair is
reported by neither this code nor the same-coordinates one.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.shape_points import (
    distance_between,
    equal_distance_differing_points,
)
from gtfs_validator.rules.equal_shape_distance_diff_coordinates import THRESHOLD_METERS
from gtfs_validator.rules.registry import file_rule

CODE = "equal_shape_distance_diff_coordinates_distance_below_threshold"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for previous, current, context in equal_distance_differing_points(feed):
        distance = distance_between(previous, current)
        if 0 < distance < THRESHOLD_METERS:
            yield Notice(
                CODE,
                Severity.WARNING,
                {**context, "actualDistanceBetweenShapePoints": distance},
            )
