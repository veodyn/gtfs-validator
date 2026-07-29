"""TripAndShapeDistanceValidator: the same overrun, but the last stop is nearly on the shape.

The warning band, and it is an `else` rather than a second test: every overrun draws exactly one of
the two codes. A last stop within 11.1 m of the shape's furthest point reads as a rounding
artefact, so the overrun is reported without claiming the trip has the wrong shape.
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

CODE = "trip_distance_exceeds_shape_distance_below_threshold"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for _trip, context in overrunning_trips(feed):
        if context["geoDistanceToShape"] <= DISTANCE_THRESHOLD_METERS:
            yield Notice(CODE, Severity.WARNING, context)
