"""The predicate FeedExpirationDateValidator's two branches share.

Upstream is one method with a `return` between the branches, so at most one of
the two notices fires for a row. Splitting them across modules means each has to
know the other's condition; expressing the 30-day case as "inside 30 days and not
inside 7" here keeps the two from drifting apart.
"""

from __future__ import annotations

import datetime

from gtfs_validator.context import Context
from gtfs_validator.rules._shared.calendars import render_gtfs_date, to_date

EXPIRY_SOON_DAYS = 7
EXPIRY_UPCOMING_DAYS = 30


# One whole Gregorian cycle. The calendar repeats exactly every 400 years, so
# shifting a date back by that much, adding days, and shifting the year forward
# again gives the same answer as adding the days directly, including across
# February 29.
GREGORIAN_CYCLE_YEARS = 400


def _plus_days(value: datetime.date, days: int) -> tuple[int, int, int]:
    """LocalDate.plusDays as a (year, month, day) triple.

    A triple rather than a date because Java's LocalDate spans year 999999999 and
    Python's date stops at 9999: plusDays(30) from 9999-12-02 is 10000-01-01
    upstream and an OverflowError here. Measured, and the notice is not
    hypothetical: at --date 9999-12-02 with a feed_end_date of 99991231 the jar
    reports feed_expiration_date30_days with suggestedExpirationDate
    "100000101". Returning None for that case suppressed the notice outright.
    """
    try:
        moved = value + datetime.timedelta(days=days)
    except OverflowError:
        shifted = value.replace(year=value.year - GREGORIAN_CYCLE_YEARS)
        moved = shifted + datetime.timedelta(days=days)
        return (moved.year + GREGORIAN_CYCLE_YEARS, moved.month, moved.day)
    return (moved.year, moved.month, moved.day)


def _render(triple: tuple[int, int, int]) -> str:
    """GtfsDate.toYYYYMMDD, widening rather than truncating past year 9999.

    Measured: the jar renders year 10000 as "100000101", nine characters, so the
    year field grows instead of wrapping.
    """
    year, month, day = triple
    return f"{year:04d}{month:02d}{day:02d}"


def expiration_context(row: dict, ctx: Context, days: int) -> dict | None:
    """The notice context when the feed expires inside `days`, else None.

    The comparison is strictly less than. Measured against the jar with the date
    pinned to 2026-06-01: an end date of 2026-06-08, exactly the 7-day suggestion,
    draws the 30-day notice rather than the 7-day one, and an end date of
    2026-07-01, exactly the 30-day suggestion, draws neither.
    """
    stored_end = row.get("feed_end_date")
    if stored_end is None:
        return None
    end = to_date(stored_end)
    end_triple = (end.year, end.month, end.day)
    suggested = _plus_days(ctx.date, days)
    if end_triple >= suggested:
        return None
    # The 7-day branch returns before the 30-day one runs upstream, so a feed
    # already inside seven days must not also draw the 30-day notice.
    if days == EXPIRY_UPCOMING_DAYS and end_triple < _plus_days(ctx.date, EXPIRY_SOON_DAYS):
        return None
    return {
        "csvRowNumber": row["_row_number"],
        "currentDate": render_gtfs_date(ctx.date),
        "feedEndDate": render_gtfs_date(end),
        "suggestedExpirationDate": _render(suggested),
    }
