"""ShapeIncreasingDistanceValidator: two shape points at one place claiming one distance.

Equal `shape_dist_traveled` and identical coordinates means the row is duplicative rather than
wrong, which is why this is a warning where the differing-coordinates case is an error.

The coordinate test is exact equality on both `shape_pt_lat` and `shape_pt_lon`, not a distance
under some tolerance: upstream compares the doubles, and only reaches the distance calculation
once they differ. So a pair 1 nanometre apart is the *other* code, and a pair whose measured
distance rounds to 0 while the coordinates differ is neither of them.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.shape_points import (
    DISTANCE,
    LATITUDE,
    LONGITUDE,
    measured_pairs,
    pair_context,
)
from gtfs_validator.rules.registry import file_rule

CODE = "equal_shape_distance_same_coordinates"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for previous, current in measured_pairs(feed):
        if previous[DISTANCE] != current[DISTANCE]:
            continue
        if current[LATITUDE] == previous[LATITUDE] and current[LONGITUDE] == previous[LONGITUDE]:
            yield Notice(CODE, Severity.WARNING, pair_context(current, previous))
