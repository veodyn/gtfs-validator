"""TripCalendarUtil: trips counted per active date, and the majority window."""

import datetime

from fakefeed import FakeFeed
from gtfs_validator.rules._shared.trip_calendar import (
    count_trips_by_date,
    majority_service_coverage,
)

WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def calendar(service_id, start, end):
    row = {"service_id": service_id, "start_date": start, "end_date": end}
    for name in WEEKDAY_NAMES:
        row[name] = 1
    return row


def d(year, month, day):
    return datetime.date(year, month, day)


def test_each_service_date_carries_that_service_s_trip_count():
    # Trips are counted per service and then added to every one of its dates, so
    # three trips over two days is 3 on each day rather than 6 spread out.
    feed = FakeFeed(
        {
            "calendar.txt": [calendar("S1", 20260601, 20260602)],
            "trips.txt": [
                {"service_id": "S1", "trip_id": "A"},
                {"service_id": "S1", "trip_id": "B"},
                {"service_id": "S1", "trip_id": "C"},
            ],
        }
    )
    assert count_trips_by_date(feed) == {d(2026, 6, 1): 3, d(2026, 6, 2): 3}


def test_two_services_sharing_a_date_add_up():
    feed = FakeFeed(
        {
            "calendar.txt": [
                calendar("S1", 20260601, 20260601),
                calendar("S2", 20260601, 20260602),
            ],
            "trips.txt": [
                {"service_id": "S1", "trip_id": "A"},
                {"service_id": "S2", "trip_id": "B"},
            ],
        }
    )
    assert count_trips_by_date(feed) == {d(2026, 6, 1): 2, d(2026, 6, 2): 1}


def test_a_frequency_row_expands_one_trip_into_many():
    # computeTripCount: one trip for the row, plus one per headway in the interval,
    # with the interval shortened by a second first because the first trip is
    # already counted. Ten hours at a ten-minute headway is 1 + (36000 - 1) // 600
    # = 60 trips.
    feed = FakeFeed(
        {
            "calendar.txt": [calendar("S1", 20260601, 20260601)],
            "trips.txt": [{"service_id": "S1", "trip_id": "A"}],
            "frequencies.txt": [
                {
                    "trip_id": "A",
                    "start_time": 8 * 3600,
                    "end_time": 18 * 3600,
                    "headway_secs": 600,
                }
            ],
        }
    )
    assert count_trips_by_date(feed) == {d(2026, 6, 1): 60}


def test_an_exact_multiple_headway_does_not_gain_a_spurious_trip():
    # The interval is shortened by a second before dividing, because the first trip
    # is already counted. An interval of exactly two headways is therefore two
    # trips, not three: 1 + (1200 - 1) // 600. An interval of exactly *one* headway
    # is a single trip, which is the same rule seen from the other end.
    for span, expected in ((1200, 2), (600, 1)):
        feed = FakeFeed(
            {
                "calendar.txt": [calendar("S1", 20260601, 20260601)],
                "trips.txt": [{"service_id": "S1", "trip_id": "A"}],
                "frequencies.txt": [
                    {
                        "trip_id": "A",
                        "start_time": 8 * 3600,
                        "end_time": 8 * 3600 + span,
                        "headway_secs": 600,
                    }
                ],
            }
        )
        assert count_trips_by_date(feed) == {d(2026, 6, 1): expected}, span


def test_a_zero_headway_contributes_only_the_row_itself():
    feed = FakeFeed(
        {
            "calendar.txt": [calendar("S1", 20260601, 20260601)],
            "trips.txt": [{"service_id": "S1", "trip_id": "A"}],
            "frequencies.txt": [
                {"trip_id": "A", "start_time": 0, "end_time": 3600, "headway_secs": 0}
            ],
        }
    )
    assert count_trips_by_date(feed) == {d(2026, 6, 1): 1}


def test_no_trips_means_no_counts():
    feed = FakeFeed({"calendar.txt": [calendar("S1", 20260601, 20260601)]})
    assert count_trips_by_date(feed) == {}


def test_the_majority_window_excludes_a_sparse_tail():
    # Nineteen days at 20 trips and one day at 1. The typical maximum is the
    # 90th-percentile count, and the threshold is three quarters of that, so the
    # sparse day falls outside the window.
    counts = {d(2026, 6, day): 20 for day in range(1, 20)}
    counts[d(2026, 6, 20)] = 1
    assert majority_service_coverage(counts) == (d(2026, 6, 1), d(2026, 6, 19))


def test_a_uniform_calendar_gives_the_whole_range():
    counts = {d(2026, 6, day): 5 for day in range(1, 11)}
    assert majority_service_coverage(counts) == (d(2026, 6, 1), d(2026, 6, 10))


def test_an_empty_count_map_has_no_coverage():
    assert majority_service_coverage({}) is None


def test_a_single_date_is_its_own_window():
    assert majority_service_coverage({d(2026, 6, 1): 4}) == (d(2026, 6, 1), d(2026, 6, 1))


def test_an_inverted_frequency_interval_truncates_towards_zero():
    # Java integer division truncates towards zero and Python's // floors, so the
    # two differ on the negative numerator an inverted interval produces. Nothing
    # in the rules implemented so far forbids such a row, so it reaches here.
    #
    # Equal endpoints: numerator -1, Java 0, so the row contributes its own trip.
    # Python's floor would give -1 and cancel it.
    #
    # end an hour before start: numerator -3601, Java -6, so the count is -5. That
    # is an absurd number of trips and it is upstream's, arrived at by the same
    # arithmetic; Python's floor would give -7 and a count of -6. Reproducing the
    # oddity is the job, not correcting it.
    for start, end, expected in (
        (8 * 3600, 8 * 3600, 1),
        (8 * 3600, 7 * 3600, -5),
    ):
        feed = FakeFeed(
            {
                "calendar.txt": [calendar("S1", 20260601, 20260601)],
                "trips.txt": [{"service_id": "S1", "trip_id": "A"}],
                "frequencies.txt": [
                    {
                        "trip_id": "A",
                        "start_time": start,
                        "end_time": end,
                        "headway_secs": 600,
                    }
                ],
            }
        )
        assert count_trips_by_date(feed) == {d(2026, 6, 1): expected}, (start, end)


def test_the_calendar_is_not_expanded_when_there_are_no_trips():
    # A feed with no trips cannot draw the notice, so the calendar must not be
    # expanded to find that out: a range spanning the supported dates would
    # allocate millions of date objects for an empty result.
    expanded = []

    class WatchingFeed(FakeFeed):
        def rows(self, filename):
            expanded.append(filename)
            return super().rows(filename)

    feed = WatchingFeed({"calendar.txt": [calendar("S1", 20260601, 20260630)]})
    assert count_trips_by_date(feed) == {}
    assert "calendar.txt" not in expanded


def test_two_frequency_rows_on_one_trip_add_up():
    feed = FakeFeed(
        {
            "calendar.txt": [calendar("S1", 20260601, 20260601)],
            "trips.txt": [{"service_id": "S1", "trip_id": "A"}],
            "frequencies.txt": [
                {"trip_id": "A", "start_time": 0, "end_time": 1200, "headway_secs": 600},
                {"trip_id": "A", "start_time": 3600, "end_time": 4800, "headway_secs": 600},
            ],
        }
    )
    assert count_trips_by_date(feed) == {d(2026, 6, 1): 4}


def test_trip_counts_wrap_like_java_ints():
    # Upstream accumulates in Java ints, which wrap. Reaching it needs an
    # adversarial feed, and the counts are sorted and thresholded afterwards, so a
    # wrapped negative selects different coverage dates. 999 hours at a one-second
    # headway is about 3.6 million trips per row, and 600 such rows overflow.
    row = {"trip_id": "A", "start_time": 0, "end_time": 999 * 3600, "headway_secs": 1}
    feed = FakeFeed(
        {
            "calendar.txt": [calendar("S1", 20260601, 20260601)],
            "trips.txt": [{"service_id": "S1", "trip_id": f"T{index}"} for index in range(600)],
            "frequencies.txt": [{**row, "trip_id": f"T{index}"} for index in range(600)],
        }
    )
    total = count_trips_by_date(feed)[d(2026, 6, 1)]
    assert total < 0
    assert -(1 << 31) <= total <= (1 << 31) - 1


def test_frequencies_are_not_read_when_there_are_no_trips():
    # Upstream tests both emptiness conditions before touching frequencies, and
    # both the frequency scan and the calendar expansion are unbounded work.
    read = []

    class WatchingFeed(FakeFeed):
        def rows(self, filename):
            read.append(filename)
            return super().rows(filename)

    feed = WatchingFeed({"frequencies.txt": [{"trip_id": "A"}], "calendar.txt": []})
    assert count_trips_by_date(feed) == {}
    assert "frequencies.txt" not in read


def test_frequencies_are_not_read_when_no_service_can_produce_a_date():
    # A non-empty period map is not enough: it stays truthy when every service is
    # zero-weekday or fully cancelled, and the rule would then scan a potentially
    # large frequency table to reach an empty result.
    read = []

    class WatchingFeed(FakeFeed):
        def rows(self, filename):
            read.append(filename)
            return super().rows(filename)

    row = calendar("S1", 20260601, 20260630)
    for name in WEEKDAY_NAMES:
        row[name] = 0
    feed = WatchingFeed(
        {
            "calendar.txt": [row],
            "trips.txt": [{"service_id": "S1", "trip_id": "A"}],
            "frequencies.txt": [
                {"trip_id": "A", "start_time": 0, "end_time": 3600, "headway_secs": 600}
            ],
        }
    )
    assert count_trips_by_date(feed) == {}
    assert "frequencies.txt" not in read
