"""ServicePeriod and CalendarUtil, ported from upstream's util package."""

import datetime

from fakefeed import FakeFeed
from gtfs_validator.rules._shared.calendars import (
    ServicePeriod,
    build_service_periods,
    render_gtfs_date,
    to_date,
    to_stored,
)

MONDAY_ONLY = 0b0000001
WEEKDAYS = 0b0011111
NO_DAYS = 0


def test_a_stored_date_round_trips():
    assert to_date(20260101) == datetime.date(2026, 1, 1)
    assert to_stored(datetime.date(2026, 1, 1)) == 20260101


def test_a_date_renders_as_eight_digits():
    # GtfsDate.toYYYYMMDD, which is what an object-typed date context field
    # carries: a string, not the integer the store holds.
    assert render_gtfs_date(datetime.date(2026, 1, 1)) == "20260101"


def test_a_weekly_pattern_expands_across_the_range():
    # 2026-01-05 is a Monday, so a Monday-only service over that week is one date.
    period = ServicePeriod(
        datetime.date(2026, 1, 5), datetime.date(2026, 1, 11), MONDAY_ONLY, set(), set()
    )
    assert period.to_dates() == [datetime.date(2026, 1, 5)]


def test_weekdays_expand_to_five_days():
    period = ServicePeriod(
        datetime.date(2026, 1, 5), datetime.date(2026, 1, 11), WEEKDAYS, set(), set()
    )
    assert len(period.to_dates()) == 5


def test_added_days_are_included_and_removed_days_win():
    # toDates adds the added days after expanding and then removes the removed
    # ones, so a date in both sets is absent.
    period = ServicePeriod(
        datetime.date(2026, 1, 5),
        datetime.date(2026, 1, 11),
        MONDAY_ONLY,
        {datetime.date(2026, 1, 6), datetime.date(2026, 1, 20)},
        {datetime.date(2026, 1, 6), datetime.date(2026, 1, 5)},
    )
    assert period.to_dates() == [datetime.date(2026, 1, 20)]


def test_a_service_with_no_active_weekday_yields_only_its_added_days():
    period = ServicePeriod(
        datetime.date(2026, 1, 5),
        datetime.date(2026, 1, 11),
        NO_DAYS,
        {datetime.date(2026, 1, 7)},
        set(),
    )
    assert period.to_dates() == [datetime.date(2026, 1, 7)]


def test_the_dates_come_back_sorted():
    period = ServicePeriod(
        datetime.date(2026, 1, 5),
        datetime.date(2026, 1, 5),
        NO_DAYS,
        {datetime.date(2026, 3, 1), datetime.date(2026, 2, 1)},
        set(),
    )
    assert period.to_dates() == [datetime.date(2026, 2, 1), datetime.date(2026, 3, 1)]


def test_a_calendar_dates_only_service_takes_its_range_from_its_added_days():
    feed = FakeFeed(
        {
            "calendar_dates.txt": [
                {"service_id": "S", "date": 20260310, "exception_type": 1},
                {"service_id": "S", "date": 20260101, "exception_type": 1},
                {"service_id": "S", "date": 20260601, "exception_type": 2},
            ]
        }
    )
    period = build_service_periods(feed)["S"]
    assert period.start == datetime.date(2026, 1, 1)
    # The removal does not widen the range: only SERVICE_ADDED moves the bounds.
    assert period.end == datetime.date(2026, 3, 10)
    assert period.to_dates() == [datetime.date(2026, 1, 1), datetime.date(2026, 3, 10)]


def test_a_service_in_both_files_combines_them():
    feed = FakeFeed(
        {
            "calendar.txt": [
                {
                    "service_id": "S",
                    "start_date": 20260105,
                    "end_date": 20260111,
                    "monday": 1,
                    "tuesday": 0,
                    "wednesday": 0,
                    "thursday": 0,
                    "friday": 0,
                    "saturday": 0,
                    "sunday": 0,
                }
            ],
            "calendar_dates.txt": [
                {"service_id": "S", "date": 20260105, "exception_type": 2},
                {"service_id": "S", "date": 20260107, "exception_type": 1},
            ],
        }
    )
    # The Monday is removed and the Wednesday added.
    assert build_service_periods(feed)["S"].to_dates() == [datetime.date(2026, 1, 7)]


def test_an_inverted_calendar_range_is_clamped_rather_than_raising():
    # createServicePeriod sets end to start and leaves the complaint to a
    # dedicated validator, so this must not raise.
    feed = FakeFeed(
        {
            "calendar.txt": [
                {
                    "service_id": "S",
                    "start_date": 20261231,
                    "end_date": 20260101,
                    "monday": 1,
                    "tuesday": 1,
                    "wednesday": 1,
                    "thursday": 1,
                    "friday": 1,
                    "saturday": 1,
                    "sunday": 1,
                }
            ]
        }
    )
    period = build_service_periods(feed)["S"]
    assert period.start == period.end == datetime.date(2026, 12, 31)


def test_a_calendar_dates_service_with_only_removals_expands_to_nothing():
    # Nothing sets a start, so it falls back to LocalDate.EPOCH with an empty
    # pattern, and the removal leaves the set empty rather than raising.
    feed = FakeFeed(
        {"calendar_dates.txt": [{"service_id": "S", "date": 20260101, "exception_type": 2}]}
    )
    period = build_service_periods(feed)["S"]
    assert period.start == datetime.date(1970, 1, 1)
    assert period.to_dates() == []


def test_a_range_ending_at_the_maximum_date_does_not_overflow():
    # A schema-valid calendar can declare 99991231, which is datetime.date.max.
    # Advancing past it raises OverflowError, so the walk has to stop at the
    # endpoint rather than incrementing past it.
    period = ServicePeriod(
        datetime.date(9999, 12, 31), datetime.date(9999, 12, 31), 0b1111111, set(), set()
    )
    assert period.to_dates() == [datetime.date(9999, 12, 31)]


def test_may_have_dates_answers_without_expanding():
    # Exact rather than conservative, so a caller can skip unbounded work when no
    # service can produce a date. A zero pattern with no surviving addition cannot.
    empty = ServicePeriod(datetime.date(2026, 1, 5), datetime.date(2026, 12, 31), NO_DAYS)
    assert not empty.may_have_dates()
    assert empty.to_dates() == []

    patterned = ServicePeriod(datetime.date(2026, 1, 5), datetime.date(2026, 1, 11), MONDAY_ONLY)
    assert patterned.may_have_dates()

    added = ServicePeriod(
        datetime.date(2026, 1, 5),
        datetime.date(2026, 1, 11),
        NO_DAYS,
        {datetime.date(2026, 2, 1)},
        set(),
    )
    assert added.may_have_dates()

    cancelled = ServicePeriod(
        datetime.date(2026, 1, 5),
        datetime.date(2026, 1, 11),
        NO_DAYS,
        {datetime.date(2026, 2, 1)},
        {datetime.date(2026, 2, 1)},
    )
    assert not cancelled.may_have_dates()
    assert cancelled.to_dates() == []
