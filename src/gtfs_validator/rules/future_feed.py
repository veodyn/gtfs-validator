"""FeedValidTodayValidator: the feed starts after the validation date.

Reports the earliest feed_start_date across every feed_info row, not the first
one. Measured: a feed with rows starting 2026-09-01 and 2026-07-01 reports
2026-07-01.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.calendars import render_gtfs_date, to_date
from gtfs_validator.rules.registry import file_rule


@file_rule(code="future_feed", severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    starts = [
        to_date(row["feed_start_date"])
        for row in feed.rows("feed_info.txt")
        if row.get("feed_start_date") is not None
    ]
    if not starts:
        return
    earliest = min(starts)
    if earliest <= ctx.date:
        return
    yield Notice(
        "future_feed",
        Severity.INFO,
        {
            "feedStartDate": render_gtfs_date(earliest),
            "currentDate": render_gtfs_date(ctx.date),
        },
    )
