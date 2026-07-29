"""FeedServiceWindowValidator, second branch: a service outside the feed period.

Per service, so one feed can draw many, and only for services referenced by
trips.txt. The day counts are ChronoUnit.DAYS.between, which is 0 on whichever
side the service sits inside the period.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.intervals import build_service_intervals
from gtfs_validator.rules._shared.service_window import feed_period, trip_service_ids, window_of
from gtfs_validator.rules.registry import file_rule


@file_rule(code="service_window_outside_feed_period", severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    period = feed_period(feed)
    if period is None:
        return
    # One expansion for both the precondition and the per-service walk. Expanding
    # long service ranges dominates the cost of these rules, and building the map
    # twice doubled it.
    intervals = build_service_intervals(feed)
    service_ids = trip_service_ids(feed)
    # The window is required too: upstream returns early unless both it and the
    # feed period exist, even though this branch does not otherwise read it.
    if window_of(intervals, service_ids) is None:
        return
    feed_start, feed_end = period
    for service_id in service_ids:
        interval = intervals.get(service_id)
        if interval is None or interval.is_empty():
            continue
        service_start = interval.first_active_date()
        service_end = interval.last_active_date()
        before = (feed_start - service_start).days if service_start < feed_start else 0
        after = (service_end - feed_end).days if service_end > feed_end else 0
        if not before and not after:
            continue
        yield Notice(
            "service_window_outside_feed_period",
            Severity.INFO,
            {
                "serviceId": service_id,
                "serviceWindowStartDate": service_start.isoformat(),
                "serviceWindowEndDate": service_end.isoformat(),
                "daysBeforeFeedStart": before,
                "daysAfterFeedEnd": after,
            },
        )
