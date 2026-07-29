"""ServiceSpreadValidator, first branch: a long inactive span inside a service.

Walks calendar.txt entities, not trip services, so a calendar_dates-only service
is invisible to it. Measured: a feed whose only service is defined purely by
calendar_dates draws nothing even with a month-long gap.

The reported dates are not the gap's own bounds. Upstream sends
`gap.start().minusDays(1)` and `gap.end().plusDays(1)`, the last active day before
the gap and the first active day after it, so they sit one day outside it on each
side while gapDurationDays is the gap's own inclusive length. Measured: a service
active on 2026-06-01 and again on 2026-06-16 reports gapStartDate 2026-06-01,
gapEndDate 2026-06-16 and gapDurationDays 14.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.intervals import ONE_DAY, build_service_intervals
from gtfs_validator.rules.registry import file_rule

# ServiceSpreadValidator.MAX_GAP_DAYS. DateInterval.lengthInDays is inclusive
# (days between plus one), so a 14-day gap is the first that fires.
MAX_GAP_DAYS = 13


@file_rule(code="big_gap_in_service", severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    intervals = build_service_intervals(feed)
    for row in feed.rows("calendar.txt"):
        service_id = row.get("service_id")
        if service_id is None:
            continue
        interval = intervals.get(service_id)
        if interval is None or interval.is_empty():
            continue
        for gap_start, gap_end in interval.gaps():
            length = (gap_end - gap_start).days + 1
            if length <= MAX_GAP_DAYS:
                continue
            yield Notice(
                "big_gap_in_service",
                Severity.INFO,
                {
                    "serviceId": service_id,
                    "gapStartDate": (gap_start - ONE_DAY).isoformat(),
                    "gapEndDate": (gap_end + ONE_DAY).isoformat(),
                    "gapDurationDays": length,
                },
            )
