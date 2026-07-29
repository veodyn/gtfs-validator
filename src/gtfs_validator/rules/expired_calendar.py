"""ExpiredCalendarValidator: a service whose last active date has passed.

Three-way logic, transcribed here so the next reader does not have to clone
upstream:

- A service defined in calendar.txt reports that row.
- A service defined only in calendar_dates.txt reports its lowest row number, and
  only when calendar.txt carries no entities at all *and* every service in the
  feed is expired. One live service suppresses the whole calendar_dates branch.
- A service whose expansion is empty is skipped before the expiry test.

Upstream reads its allCalendarAreExpired flag inside the loop that mutates it, so
the in-loop guard depends on Java's HashMap iteration order. The post-loop check
is the one that decides and it is order-independent, so only that is reproduced.

Measured against the jar with the date pinned to 2026-06-01, six feeds:
calendar.txt with an expired service reports its row; a header-only calendar.txt
with two expired calendar_dates services reports each at its lowest row; the same
shape with one live service reports nothing; a mixed calendar.txt reports only
the expired service; a service whose added day is also removed reports nothing;
and a live calendar.txt alongside an expired calendar_dates-only service reports
nothing.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.calendars import build_service_periods
from gtfs_validator.rules.registry import file_rule


@file_rule(code="expired_calendar", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # The *first* row per service_id, not the last. A duplicate service_id draws
    # duplicate_key and both rows are still stored, and upstream reads the row
    # number through byServiceId, whose index keeps the first entity even though
    # the service-period map is built from the last. Measured: for two calendar
    # rows sharing an expired service_id the jar reports csvRowNumber 2.
    calendar_rows: dict[str, int] = {}
    for row in feed.rows("calendar.txt"):
        service_id = row.get("service_id")
        if service_id is None:
            continue
        row_number = row["_row_number"]
        if service_id not in calendar_rows or row_number < calendar_rows[service_id]:
            calendar_rows[service_id] = row_number
    first_date_row: dict[str, int] = {}
    for row in feed.rows("calendar_dates.txt"):
        service_id = row.get("service_id")
        if service_id is None:
            continue
        row_number = row["_row_number"]
        if service_id not in first_date_row or row_number < first_date_row[service_id]:
            first_date_row[service_id] = row_number

    from_calendar: list[tuple[int, str]] = []
    from_calendar_dates: list[tuple[int, str]] = []
    all_expired = True
    # One service expanded at a time, so only one date list is live. Sharing a
    # memoised map with trip_coverage_not_active_for_next7_days saved the second
    # expansion and retained every list instead, which is unbounded in the
    # calendar's width and worthless whenever that rule returns early.
    for service_id, period in build_service_periods(feed).items():
        dates = period.to_dates()
        if not dates:
            continue
        if dates[-1] < ctx.date:
            if service_id in calendar_rows:
                from_calendar.append((calendar_rows[service_id], service_id))
            else:
                # orElse(0) upstream, for a service that somehow has no rows.
                from_calendar_dates.append((first_date_row.get(service_id, 0), service_id))
        else:
            all_expired = False

    reported = list(from_calendar)
    if not calendar_rows and all_expired:
        reported.extend(from_calendar_dates)
    # Sorted by row number, as upstream sorts before adding.
    for row_number, service_id in sorted(reported):
        yield Notice(
            "expired_calendar",
            Severity.WARNING,
            {"csvRowNumber": row_number, "serviceId": service_id},
        )
