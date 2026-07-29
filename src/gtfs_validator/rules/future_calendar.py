"""FeedServiceWindowValidator, first branch: every service starts in the future.

Fires *before* the feed_info guard upstream, so it reports on a feed with no
feed_info.txt at all. Measured: the jar reports it for such a feed.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.service_window import total_service_window
from gtfs_validator.rules.registry import file_rule

FEED_INFO = "feed_info.txt"


@file_rule(code="future_calendar", severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # FeedServiceWindowValidator is injected with feed_info.txt as well as the calendar tables and
    # trips.txt, so a failed feed_info.txt skips it. This rule is the only one of the validator's
    # three that never reads feed_info, so it is the only one the raise-on-read gate misses:
    # measured on a feed_info.txt with a short row, where the jar reports nothing and we reported
    # future_calendar. Its siblings read feed_period, which touches feed_info, and are gated
    # already.
    if feed.dependency_failed(FEED_INFO):
        return
    window = total_service_window(feed)
    if window is None or window[0] <= ctx.date:
        return
    yield Notice(
        "future_calendar",
        Severity.INFO,
        {
            # LocalDate.toString(), ISO with dashes, not GtfsDate's eight digits.
            # The manifest types both fields as string rather than object, which is
            # the signal, and the jar prints "2026-09-01".
            "minServiceStartDate": window[0].isoformat(),
            "currentDate": ctx.date.isoformat(),
        },
    )
