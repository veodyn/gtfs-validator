"""The feed-level window helpers in rules._shared.service_window.

Split from test_intervals.py alongside the source split: interval expansion
stays there, everything about the window across services and the feed period
lives here.
"""

import datetime

from fakefeed import FakeFeed
from gtfs_validator.rules._shared.service_window import feed_period, total_service_window

MONDAY_ONLY = 0b0000001
ALL_DAYS = 0b1111111


def d(year, month, day):
    return datetime.date(year, month, day)


def calendar(service_id, days, start, end):
    row = {"service_id": service_id, "start_date": start, "end_date": end}
    for index, name in enumerate(
        ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    ):
        row[name] = (days >> index) & 1
    return row


def test_a_service_used_by_no_trip_is_outside_the_window():
    feed = FakeFeed(
        {
            "calendar.txt": [
                calendar("USED", ALL_DAYS, 20260105, 20260109),
                calendar("UNUSED", ALL_DAYS, 20250101, 20271231),
            ],
            "trips.txt": [{"service_id": "USED"}],
        }
    )
    assert total_service_window(feed) == (d(2026, 1, 5), d(2026, 1, 9))


def test_a_feed_with_no_trips_has_no_window():
    feed = FakeFeed({"calendar.txt": [calendar("S1", ALL_DAYS, 20260105, 20260109)]})
    assert total_service_window(feed) is None


def test_a_trip_service_with_no_active_date_is_skipped():
    feed = FakeFeed(
        {
            "calendar.txt": [calendar("S1", 0, 20260105, 20260109)],
            "trips.txt": [{"service_id": "S1"}],
        }
    )
    assert total_service_window(feed) is None


def test_a_calendar_dates_only_service_still_reaches_the_window():
    feed = FakeFeed(
        {
            "calendar_dates.txt": [{"service_id": "S1", "date": 20260210, "exception_type": 1}],
            "trips.txt": [{"service_id": "S1"}],
        }
    )
    assert total_service_window(feed) == (d(2026, 2, 10), d(2026, 2, 10))


def test_the_feed_period_reads_only_the_first_row():
    feed = FakeFeed(
        {
            "feed_info.txt": [
                {"feed_start_date": 20260101, "feed_end_date": 20260131},
                {"feed_start_date": 20250101, "feed_end_date": 20271231},
            ]
        }
    )
    assert feed_period(feed) == (d(2026, 1, 1), d(2026, 1, 31))


def test_a_feed_period_missing_either_date_is_none():
    for start, end in ((20260101, None), (None, 20260131), (None, None)):
        feed = FakeFeed({"feed_info.txt": [{"feed_start_date": start, "feed_end_date": end}]})
        assert feed_period(feed) is None, (start, end)
    assert feed_period(FakeFeed({})) is None
