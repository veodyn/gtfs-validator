"""ServiceSpreadValidator, second branch: a service running years out.

Walks calendar.txt entities like its sibling, so a calendar_dates-only service is
invisible to it.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.intervals import build_service_intervals
from gtfs_validator.rules.registry import file_rule

# ServiceSpreadValidator.MAX_FUTURE_EXTENT_DAYS, spelled 2 * 365 upstream: two
# calendar years of days, not two calendar years, so a leap day shortens it by one
# in date terms. Measured against a pinned date of 2026-06-01: a service ending
# 2028-05-31 is 730 days out and draws nothing, and 2028-06-01 is 731 and draws it.
MAX_FUTURE_EXTENT_DAYS = 2 * 365


@file_rule(code="service_extends_far_in_the_future", severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    intervals = build_service_intervals(feed)
    for row in feed.rows("calendar.txt"):
        service_id = row.get("service_id")
        if service_id is None:
            continue
        interval = intervals.get(service_id)
        if interval is None or interval.is_empty():
            continue
        last = interval.last_active_date()
        if (last - ctx.date).days <= MAX_FUTURE_EXTENT_DAYS:
            continue
        yield Notice(
            "service_extends_far_in_the_future",
            Severity.INFO,
            {"serviceId": service_id, "serviceWindowEndDate": last.isoformat()},
        )
