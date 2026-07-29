"""ShapeToStopMatchingValidator: a stop far from where its `shape_dist_traveled` puts it.

The same 100 m threshold as the geo code, measured against a different match: the point on the
shape whose `shape_dist_traveled` equals the stop's, rather than the point nearest the stop. So this
fires on a stop sitting exactly on its shape whose distance value names somewhere else.

Two things make it rarer than it looks. It runs only when **both** the trip's last stop and the
shape's last point carry a positive `shape_dist_traveled`, and it is suppressed for any stop the geo
pass has already reported, which is most stops that are genuinely far from the shape. The
large-station multiplier does not apply here, so a rail terminus tolerated at 400 m by the geo pass
is judged at 100 m by this one.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.stop_to_shape_problems import TOO_FAR_USER_DISTANCE, contexts_for
from gtfs_validator.rules.registry import file_rule


@file_rule(code=TOO_FAR_USER_DISTANCE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for context in contexts_for(feed, TOO_FAR_USER_DISTANCE):
        yield Notice(TOO_FAR_USER_DISTANCE, Severity.WARNING, context)
