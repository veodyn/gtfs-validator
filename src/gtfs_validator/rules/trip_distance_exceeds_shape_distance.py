"""TripAndShapeDistanceValidator: a trip claiming distance its shape does not have.

The error band. Its sibling below the threshold takes the same overrun when the last stop is close
enough to the shape's end that the mismatch looks like a rounding artefact rather than the wrong
shape. Upstream splits on 11.1 m of *geographic* distance, so the size of the overrun does not
decide which code fires.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.trip_shape_distance import (
    DISTANCE_THRESHOLD_METERS,
    overrunning_trips,
)
from gtfs_validator.rules.registry import file_rule

CODE = "trip_distance_exceeds_shape_distance"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for _trip, context in overrunning_trips(feed):
        if context["geoDistanceToShape"] > DISTANCE_THRESHOLD_METERS:
            yield Notice(CODE, Severity.ERROR, context)
