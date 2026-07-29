"""The feed-level service window FeedServiceWindowValidator derives.

Split from `intervals`, which owns expanding calendars into per-service
intervals, when the two together passed the file-size limit. Everything here is
about the window *across* services and the feed period it is compared against;
nothing here expands a calendar itself.
"""

from __future__ import annotations

import datetime

from gtfs_validator.javahash import multimap_order
from gtfs_validator.rules._shared.calendars import to_date
from gtfs_validator.rules._shared.intervals import ServiceInterval, build_service_intervals


def trip_service_ids(feed) -> list[str]:
    """The service ids referenced by trips.txt, in the container's key order.

    FeedServiceWindowValidator iterates `tripTable.byServiceIdMap().keySet()`, so
    a service defined in calendar.txt and used by no trip is invisible to all
    three of its notices. ServiceSpreadValidator walks calendar.txt entities
    instead, so its service set is different.

    The order is the generated container's: an `ArrayListMultimap.create()`
    backed by a HashMap, which is what `multimap_order` models. Below the export
    cap the sorted report hides the difference from file order; above it, which
    1,000 samples survive depends on emission order. Measured on the 1091-LU
    corpus feed, whose service_window_outside_feed_period count passes the cap.
    """
    seen: dict[str, None] = {}
    for row in feed.rows("trips.txt"):
        service_id = row.get("service_id")
        if service_id is not None:
            seen.setdefault(service_id)
    return multimap_order(seen)


def window_of(
    intervals: dict[str, ServiceInterval], service_ids: list[str]
) -> tuple[datetime.date, datetime.date] | None:
    """The earliest and latest active date across the named services.

    Takes a prebuilt map so a caller needing both the window and the per-service
    intervals expands the calendar once. Expanding long service ranges dominates
    the cost of these rules.
    """
    start: datetime.date | None = None
    end: datetime.date | None = None
    for service_id in service_ids:
        interval = intervals.get(service_id)
        if interval is None or interval.is_empty():
            continue
        first, last = interval.first_active_date(), interval.last_active_date()
        start = first if start is None or first < start else start
        end = last if end is None or last > end else end
    if start is None or end is None:
        return None
    return (start, end)


def total_service_window(feed) -> tuple[datetime.date, datetime.date] | None:
    """The window across every trip's service, for a caller needing only that.

    None when no trip service has any active date, which is the condition
    FeedServiceWindowValidator tests before each of its three notices.
    """
    return window_of(build_service_intervals(feed), trip_service_ids(feed))


def feed_period(feed) -> tuple[datetime.date, datetime.date] | None:
    """feed_info's start and end dates, from row zero only.

    `feedInfoTable.getEntities().get(0)`, not merged across rows: a second
    feed_info row is ignored here, unlike `future_feed`, which takes the minimum
    across rows. None when there is no feed_info or when either date is absent,
    both of which make the two rules that read this return early.
    """
    for row in feed.rows("feed_info.txt"):
        start, end = row.get("feed_start_date"), row.get("feed_end_date")
        if start is None or end is None:
            return None
        return (to_date(start), to_date(end))
    return None
