"""FeedServiceWindowValidator, third branch: the feed outlives its services.

THRESHOLD_DAYS is 14 and the comparisons are strict, so a feed period exceeding
the service window by exactly 14 days on each end does not fire. Measured: 14 days
of excess draws nothing and 15 days draws the notice.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.service_window import feed_period, total_service_window
from gtfs_validator.rules.registry import file_rule

# Compared as day differences rather than by shifting the window dates, because a
# service beginning in the first 14 days of year 1 or ending in the last 14 of year
# 9999 is schema-valid and shifting past either bound raises OverflowError. Java's
# LocalDate computes across both.
THRESHOLD_DAYS = 14


@file_rule(code="feed_valid_beyond_total_service_window", severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    period = feed_period(feed)
    window = total_service_window(feed)
    if period is None or window is None:
        return
    feed_start, feed_end = period
    window_start, window_end = window
    starts_too_early = (window_start - feed_start).days > THRESHOLD_DAYS
    ends_too_late = (feed_end - window_end).days > THRESHOLD_DAYS
    if not (starts_too_early or ends_too_late):
        return
    yield Notice(
        "feed_valid_beyond_total_service_window",
        Severity.INFO,
        {
            "feedStartDate": feed_start.isoformat(),
            "feedEndDate": feed_end.isoformat(),
            "serviceWindowStartDate": window_start.isoformat(),
            "serviceWindowEndDate": window_end.isoformat(),
        },
    )
