"""ShapeToStopMatchingValidator: two consecutive stops whose shape positions run backwards.

Reported when no monotonic assignment of stops to shape positions exists at all, not merely when
the two nearest points happen to be out of order. The matcher tries every candidate place for every
stop first; this fires only once the forward pass runs out of feasible assignments, and then names
the stop it gave up on and the one before it.

The two stops are numbered by role, not by position along the shape: the `1` fields are the stop the
matching failed at, and the `2` fields the one before it in `stop_sequence`. So `stopTimeCsvRowNumber1`
is normally the *larger* row number of the pair.

At most one of these per trip: the walk returns as soon as it fails.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.stop_to_shape_problems import OUT_OF_ORDER, contexts_for
from gtfs_validator.rules.registry import file_rule


@file_rule(code=OUT_OF_ORDER, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for context in contexts_for(feed, OUT_OF_ORDER):
        yield Notice(OUT_OF_ORDER, Severity.WARNING, context)
