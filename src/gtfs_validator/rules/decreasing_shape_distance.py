"""ShapeIncreasingDistanceValidator: `shape_dist_traveled` going backwards along a shape.

Sorted by `shape_pt_sequence`, a shape's distances must not decrease. This is the first of the
validator's four branches and the only one whose notice fields are inverted.

**The inversion is upstream's and is reproduced deliberately.** The call site is
`new DecreasingShapeDistanceNotice(prev, curr)` and the constructor is declared
`DecreasingShapeDistanceNotice(GtfsShape current, GtfsShape previous)`, so the arguments are
swapped: `csvRowNumber` names the *earlier* point and `prevCsvRowNumber` the later one. The other
three codes on this validator take `(previous, current)` and read the natural way round.

Measured on a three-point shape whose distances run 0, 111.2, 50.0 in rows 2, 3 and 4: the jar
reports `csvRowNumber` 3 with `shapeDistTraveled` 111.2, and `prevCsvRowNumber` 4 with
`prevShapeDistTraveled` 50.0. Writing it the way the field names suggest inverts both pairs.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.shape_points import DISTANCE, measured_pairs, pair_context
from gtfs_validator.rules.registry import file_rule

CODE = "decreasing_shape_distance"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for previous, current in measured_pairs(feed):
        if previous[DISTANCE] > current[DISTANCE]:
            # Swapped, matching upstream's constructor call. See the module docstring.
            yield Notice(CODE, Severity.ERROR, pair_context(previous, current))
