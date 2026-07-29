"""ServiceInterval, an interval map rather than a date set.

Separate from calendars.py deliberately: exceptions apply in row order here, and
a date removed then re-added ends up present. Measured, see the plan 5 notes.
"""

import datetime

from fakefeed import FakeFeed
from gtfs_validator.rules._shared.intervals import ServiceInterval, build_service_intervals

MONDAY_ONLY = 0b0000001
ALL_DAYS = 0b1111111


def d(year, month, day):
    return datetime.date(year, month, day)


def test_a_zero_pattern_adds_nothing():
    # addInterval returns before touching the range when the pattern is 0, so a
    # calendar row with no active days contributes nothing while its
    # calendar_dates rows still do.
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 11), 0)
    assert interval.is_empty()


def test_a_full_pattern_becomes_one_run():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 11), ALL_DAYS)
    assert interval.intervals() == [(d(2026, 1, 5), d(2026, 1, 11))]


def test_a_single_weekday_becomes_one_run_per_week():
    # 2026-01-05, 12 and 19 are Mondays, so a Monday-only three-week range is
    # three one-day runs rather than one long one.
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 19), MONDAY_ONLY)
    assert interval.intervals() == [
        (d(2026, 1, 5), d(2026, 1, 5)),
        (d(2026, 1, 12), d(2026, 1, 12)),
        (d(2026, 1, 19), d(2026, 1, 19)),
    ]


def test_adjacent_runs_merge():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 6), ALL_DAYS)
    interval.add_date(d(2026, 1, 7))
    assert interval.intervals() == [(d(2026, 1, 5), d(2026, 1, 7))]


def test_a_date_inside_an_existing_run_changes_nothing():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 9), ALL_DAYS)
    interval.add_date(d(2026, 1, 7))
    assert interval.intervals() == [(d(2026, 1, 5), d(2026, 1, 9))]


def test_removing_a_middle_date_splits_a_run():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 9), ALL_DAYS)
    interval.remove_date(d(2026, 1, 7))
    assert interval.intervals() == [
        (d(2026, 1, 5), d(2026, 1, 6)),
        (d(2026, 1, 8), d(2026, 1, 9)),
    ]


def test_removing_an_edge_date_trims_a_run():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 9), ALL_DAYS)
    interval.remove_date(d(2026, 1, 5))
    interval.remove_date(d(2026, 1, 9))
    assert interval.intervals() == [(d(2026, 1, 6), d(2026, 1, 8))]


def test_removing_the_only_date_empties_the_map():
    interval = ServiceInterval()
    interval.add_date(d(2026, 1, 5))
    interval.remove_date(d(2026, 1, 5))
    assert interval.is_empty()


def test_removing_a_date_outside_every_run_does_nothing():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 6), ALL_DAYS)
    interval.remove_date(d(2026, 2, 1))
    interval.remove_date(d(2025, 1, 1))
    assert interval.intervals() == [(d(2026, 1, 5), d(2026, 1, 6))]


def test_a_removed_date_can_be_added_back():
    # The ordering that set semantics gets wrong. Measured against the jar: a
    # calendar_dates removal followed by an addition of the same date leaves the
    # date active, and the service window extends to it.
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 12), MONDAY_ONLY)
    interval.remove_date(d(2026, 1, 20))
    interval.add_date(d(2026, 1, 20))
    assert interval.last_active_date() == d(2026, 1, 20)


def test_an_added_date_can_be_removed_again():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 12), MONDAY_ONLY)
    interval.add_date(d(2026, 1, 20))
    interval.remove_date(d(2026, 1, 20))
    assert interval.last_active_date() == d(2026, 1, 12)


def test_gaps_are_the_space_between_runs():
    interval = ServiceInterval()
    interval.add_date(d(2026, 1, 1))
    interval.add_date(d(2026, 1, 10))
    # The gap is the inactive span itself, 2 through 9 inclusive.
    assert list(interval.gaps()) == [(d(2026, 1, 2), d(2026, 1, 9))]


def test_a_single_run_has_no_gaps():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 9), ALL_DAYS)
    assert list(interval.gaps()) == []


def test_first_and_last_active_dates_span_every_run():
    interval = ServiceInterval()
    interval.add_date(d(2026, 3, 1))
    interval.add_date(d(2026, 1, 1))
    assert interval.first_active_date() == d(2026, 1, 1)
    assert interval.last_active_date() == d(2026, 3, 1)


def calendar(service_id, days, start, end):
    row = {"service_id": service_id, "start_date": start, "end_date": end}
    for index, name in enumerate(
        ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    ):
        row[name] = (days >> index) & 1
    return row


def test_exceptions_apply_in_row_order():
    # The measured case: remove then add leaves the date active, and the reverse
    # order does not. Set semantics would give the later answer for both.
    removed_then_added = FakeFeed(
        {
            "calendar.txt": [calendar("S1", MONDAY_ONLY, 20260105, 20260112)],
            "calendar_dates.txt": [
                {"service_id": "S1", "date": 20260120, "exception_type": 2},
                {"service_id": "S1", "date": 20260120, "exception_type": 1},
            ],
        }
    )
    added_then_removed = FakeFeed(
        {
            "calendar.txt": [calendar("S1", MONDAY_ONLY, 20260105, 20260112)],
            "calendar_dates.txt": [
                {"service_id": "S1", "date": 20260120, "exception_type": 1},
                {"service_id": "S1", "date": 20260120, "exception_type": 2},
            ],
        }
    )
    assert build_service_intervals(removed_then_added)["S1"].last_active_date() == d(2026, 1, 20)
    assert build_service_intervals(added_then_removed)["S1"].last_active_date() == d(2026, 1, 12)


def test_an_unrecognized_exception_type_is_ignored_rather_than_removing():
    # ServiceIntervalCache switches on the enum with a default that ignores the
    # row, while createServicePeriod files anything not SERVICE_ADDED under
    # removals. This is the second measured difference between the two helpers.
    # Measured: an exception_type of 7 naming the service's last active day leaves
    # the jar's window ending on that day, so the row is ignored.
    feed = FakeFeed(
        {
            "calendar.txt": [calendar("S1", ALL_DAYS, 20260601, 20260630)],
            "calendar_dates.txt": [{"service_id": "S1", "date": 20260630, "exception_type": 7}],
        }
    )
    assert build_service_intervals(feed)["S1"].last_active_date() == d(2026, 6, 30)


def test_an_out_of_enum_exception_type_stored_as_unrecognized_is_ignored():
    # The typing stage folds an out-of-enum value to UNRECOGNIZED, which is -1, so
    # that is what actually reaches this code rather than the raw 7.
    feed = FakeFeed(
        {
            "calendar.txt": [calendar("S1", ALL_DAYS, 20260601, 20260630)],
            "calendar_dates.txt": [{"service_id": "S1", "date": 20260630, "exception_type": -1}],
        }
    )
    assert build_service_intervals(feed)["S1"].last_active_date() == d(2026, 6, 30)


def test_a_service_named_only_by_an_ignored_exception_is_still_registered():
    # computeIfAbsent runs before the switch upstream, so the service exists with
    # an empty interval rather than being absent from the map.
    feed = FakeFeed(
        {"calendar_dates.txt": [{"service_id": "S1", "date": 20260630, "exception_type": 7}]}
    )
    intervals = build_service_intervals(feed)
    assert "S1" in intervals
    assert intervals["S1"].is_empty()


def test_a_run_ending_at_the_maximum_date_can_be_extended():
    # 99991231 is schema-valid, and testing adjacency by constructing the day after
    # a run's end raises OverflowError there.
    interval = ServiceInterval()
    interval.add_date(d(9999, 12, 30))
    interval.add_date(d(9999, 12, 31))
    assert interval.intervals() == [(d(9999, 12, 30), d(9999, 12, 31))]


def test_a_date_added_next_to_a_maximum_date_run_does_not_overflow():
    interval = ServiceInterval()
    interval.add_date(d(9999, 12, 31))
    interval.add_date(d(2026, 1, 1))
    assert interval.first_active_date() == d(2026, 1, 1)
    assert interval.last_active_date() == d(9999, 12, 31)
