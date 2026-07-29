"""ServiceInterval batching, flushing and scale behaviour.

Split from test_intervals.py for the file-size limit: expansion semantics stay
there, everything about batch merging, bounded flushing and construction cost
lives here.
"""

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.rules._shared.intervals import ServiceInterval, build_service_intervals

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


def test_a_sparse_century_long_service_builds_quickly():
    # A Monday-only service over a century is ~5,200 runs. Scanning every existing
    # run per insert made this quadratic; upstream uses a TreeMap and finds only the
    # neighbours. Asserting the run count rather than a wall-clock time keeps the
    # test deterministic, and it would not finish at all under the old behaviour on
    # the millennium-scale ranges a feed may declare.
    interval = ServiceInterval()
    interval.add_interval(d(1926, 1, 4), d(2026, 1, 5), MONDAY_ONLY)
    runs = interval.intervals()
    assert len(runs) == 5219
    assert runs[0] == (d(1926, 1, 4), d(1926, 1, 4))
    assert runs[-1] == (d(2026, 1, 5), d(2026, 1, 5))
    assert next(interval.gaps()) == (d(1926, 1, 5), d(1926, 1, 10))


def test_a_batch_of_additions_merges_in_any_order():
    # Additions commute, so a descending batch gives the same runs as an ascending
    # one. The batch path exists because applying them one at a time shifts the
    # list on every insert.
    ascending = ServiceInterval()
    ascending.add_dates([d(2026, 1, day) for day in (1, 2, 3, 10, 11)])
    descending = ServiceInterval()
    descending.add_dates([d(2026, 1, day) for day in (11, 10, 3, 2, 1)])
    assert ascending.intervals() == descending.intervals()
    assert ascending.intervals() == [
        (d(2026, 1, 1), d(2026, 1, 3)),
        (d(2026, 1, 10), d(2026, 1, 11)),
    ]


def test_a_batch_merges_into_existing_runs():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 6), ALL_DAYS)
    interval.add_dates([d(2026, 1, 7), d(2026, 1, 20)])
    assert interval.intervals() == [
        (d(2026, 1, 5), d(2026, 1, 7)),
        (d(2026, 1, 20), d(2026, 1, 20)),
    ]


def test_a_batched_build_still_respects_removal_order():
    # The batch is flushed when a removal for that service arrives, so ordering
    # between an addition and a removal survives batching.
    feed = FakeFeed(
        {
            "calendar_dates.txt": [
                {"service_id": "S1", "date": 20260110, "exception_type": 1},
                {"service_id": "S1", "date": 20260120, "exception_type": 1},
                {"service_id": "S1", "date": 20260120, "exception_type": 2},
                {"service_id": "S1", "date": 20260130, "exception_type": 1},
            ]
        }
    )
    assert build_service_intervals(feed)["S1"].intervals() == [
        (d(2026, 1, 10), d(2026, 1, 10)),
        (d(2026, 1, 30), d(2026, 1, 30)),
    ]


def test_a_removal_before_its_addition_still_leaves_the_date_active():
    feed = FakeFeed(
        {
            "calendar_dates.txt": [
                {"service_id": "S1", "date": 20260120, "exception_type": 2},
                {"service_id": "S1", "date": 20260120, "exception_type": 1},
            ]
        }
    )
    assert build_service_intervals(feed)["S1"].intervals() == [(d(2026, 1, 20), d(2026, 1, 20))]


def test_an_inverted_range_raises_rather_than_adding_nothing():
    # addInterval opens with a Preconditions.checkArgument, so an inverted calendar
    # row aborts the whole interval build. Measured: on a feed whose calendar runs
    # 20261231 to 20260101 the jar reports two runtime_exception_in_validator_error
    # entries naming FeedServiceWindowValidator and ServiceSpreadValidator and none
    # of their five notices. Silently adding nothing let a later calendar_dates
    # addition produce a window upstream never reports.
    interval = ServiceInterval()
    with pytest.raises(ValueError, match="must be before or equal"):
        interval.add_interval(d(2026, 12, 31), d(2026, 1, 1), ALL_DAYS)
    # Before the zero-pattern return, so a zero pattern does not excuse it.
    with pytest.raises(ValueError, match="must be before or equal"):
        interval.add_interval(d(2026, 12, 31), d(2026, 1, 1), 0)


def test_an_equal_start_and_end_is_not_inverted():
    interval = ServiceInterval()
    interval.add_interval(d(2026, 1, 5), d(2026, 1, 5), ALL_DAYS)
    assert interval.intervals() == [(d(2026, 1, 5), d(2026, 1, 5))]


def test_a_long_run_of_additions_is_flushed_in_bounded_batches():
    # Additions commute across batches too, so flushing early is exact. The result
    # must be identical to one unbounded batch: 25,000 consecutive dates coalesce
    # into a single run even though the buffer holds at most 10,000.
    rows = [
        {"service_id": "S1", "date": 20260101, "exception_type": 1},
    ]
    base = d(2026, 1, 1)
    rows = [
        {
            "service_id": "S1",
            "date": int((base + datetime.timedelta(days=offset)).strftime("%Y%m%d")),
            "exception_type": 1,
        }
        for offset in range(25000)
    ]
    intervals = build_service_intervals(FakeFeed({"calendar_dates.txt": rows}))
    assert intervals["S1"].intervals() == [(base, base + datetime.timedelta(days=24999))]


def test_the_interval_map_is_built_once_per_feed():
    # Upstream shares one ServiceIntervalCache between its two validators; five rule
    # modules here would otherwise expand every calendar five times.
    feed = FakeFeed({"calendar.txt": [calendar("S1", ALL_DAYS, 20260101, 20260131)]})
    first = build_service_intervals(feed)
    assert build_service_intervals(feed) is first
