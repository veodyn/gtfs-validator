"""ShapeIncreasingDistanceValidator: one distance claimed at two places far enough apart to matter.

Equal `shape_dist_traveled` at differing coordinates is an error once the points are at least
1.11 m apart, and a warning below that. The threshold and the reported distance both come from
`S2Earth.getDistanceMeters`.

The 1.11 m constant is not a rounded metre and not a unit of latitude: 0.00001 degrees of latitude
measures 1.1119510126348764 m, just over it. A fixture meant to sit either side of the boundary
has to be measured rather than reasoned about.

`actualDistanceBetweenShapePoints` is reported to full double precision, so divergence 12 applies:
0.8% of coordinate pairs render a different final digit, because the value depends on a libm that
is not specified to the last bit and that upstream's own JVM does not fix either.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.shape_points import (
    distance_between,
    equal_distance_differing_points,
)
from gtfs_validator.rules.registry import file_rule

CODE = "equal_shape_distance_diff_coordinates"
# ShapeIncreasingDistanceValidator.DISTANCE_THRESHOLD.
THRESHOLD_METERS = 1.11


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for previous, current, context in equal_distance_differing_points(feed):
        distance = distance_between(previous, current)
        if distance >= THRESHOLD_METERS:
            yield Notice(
                CODE,
                Severity.ERROR,
                {**context, "actualDistanceBetweenShapePoints": distance},
            )
