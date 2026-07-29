"""ShapeToStopMatchingValidator: a stop more than 100 m from the shape its trip follows.

Reported once per stop per shape, however many trips visit it, and never for a stop the
user-distance pass has already named. See `_shared/stop_to_shape_problems` for the state that makes
that so.

The threshold is 100 m, quadrupled to 400 m for the first and last stop of a **rail** trip:
upstream's tolerance for agency shapes that stop short of a main station's platforms.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.stop_to_shape_problems import TOO_FAR, contexts_for
from gtfs_validator.rules.registry import file_rule


@file_rule(code=TOO_FAR, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for context in contexts_for(feed, TOO_FAR):
        yield Notice(TOO_FAR, Severity.WARNING, context)
