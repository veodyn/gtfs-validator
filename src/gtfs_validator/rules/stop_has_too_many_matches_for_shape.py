"""ShapeToStopMatchingValidator: a stop the shape comes close to more than 20 separate times.

`matchCount` counts **local minima** of the distance from the stop to the shape, not close
segments. A stop beside a long straight run of shape has one match; a stop the shape genuinely
returns to twenty-one times has twenty-one. A zig-zag that never leaves the 100 m threshold counts
once however many turns it makes, which is what a first attempt at a fixture got wrong.

Unlike the too-far codes this is not deduplicated by stop id, so a shape whose several trips all
visit the offending stop reports it once per distinct trip stop pattern.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.stop_to_shape_problems import TOO_MANY_MATCHES, contexts_for
from gtfs_validator.rules.registry import file_rule


@file_rule(code=TOO_MANY_MATCHES, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for context in contexts_for(feed, TOO_MANY_MATCHES):
        yield Notice(TOO_MANY_MATCHES, Severity.WARNING, context)
