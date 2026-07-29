"""TripUsageValidator, StopTimesTripBlockOrderValidator and LocationHasStopTimesValidator.

The first test compares against the jar's output on `usefeed`. The rest drive the rules
through `FakeFeed` on variations `usefeed` does not contain, and each of those was measured
on its own probe feed before being written down. Where a test says "measured", that is what
it means.

Fixtures live in `usagefeed`; the transfer, block and in-seat rules that shared them are in
`test_rules_transfers.py`.
"""

from __future__ import annotations

import pytest

from fakefeed import FakeFeed
from gtfs_validator.rules import registry
from usagefeed import CTX, MEASURED, TABLES, fire, stop_time


@pytest.mark.parametrize(("code", "expected"), sorted(MEASURED.items()))
def test_usage_rule_matches_the_jar(code, expected):
    got = fire(code)
    # Compared as a sorted multiset here because this feed is far under the sample cap. Above
    # it the order *is* the contract, since it decides which thousand notices a report keeps;
    # that is what test_the_sample_cap_keeps_the_jars_thousand covers.
    assert sorted(got, key=lambda row: sorted(row.items())) == sorted(
        expected, key=lambda row: sorted(row.items())
    )


def test_a_trip_is_unsorted_when_its_rows_are_merely_split():
    """T1's stop_sequence rises the whole way and it is still reported, because its rows
    span 2 to 10 while it has only three of them. The check is contiguity *or* ordering, and
    the contiguity half is easy to miss: the notice's name only suggests the other one."""
    got = fire("unsorted_stop_times")
    assert {row["tripId"] for row in got} == {"T1", "T3", "T4", "T5"}
    contiguous_and_sorted = {
        "stop_times.txt": [stop_time(2, "T9", "S1", 1), stop_time(3, "T9", "S4", 2)],
    }
    assert fire("unsorted_stop_times", contiguous_and_sorted) == []


def test_an_equal_stop_sequence_counts_as_unsorted():
    """The comparison is `<=`, so a repeated stop_sequence is reported as well as a
    decreasing one."""
    tables = {"stop_times.txt": [stop_time(2, "T9", "S1", 1), stop_time(3, "T9", "S4", 1)]}
    assert fire("unsorted_stop_times", tables) == [
        {"tripId": "T9", "startCsvRowNumber": 2, "endCsvRowNumber": 3}
    ]


def test_a_stop_reached_only_through_a_location_group_is_exempt():
    """S3 has no stop time of its own, and is not reported because a stop time names the
    location group it belongs to. Dropping that exemption reports a stop the jar accepts."""
    assert [row["stopId"] for row in fire("stop_without_stop_time")] == ["S2"]
    without_groups = {key: value for key, value in TABLES.items() if "location_group" not in key}
    assert sorted(row["stopId"] for row in fire("stop_without_stop_time", without_groups)) == [
        "S2",
        "S3",
    ]


def test_only_a_plain_stop_is_expected_to_have_stop_times():
    """An entrance with no stop times is fine and a station with one is not, so the two
    halves of this validator are opposites rather than variations."""
    assert [row["stopId"] for row in fire("location_with_unexpected_stop_time")] == ["ST1"]
    assert "E1" not in {row["stopId"] for row in fire("stop_without_stop_time")}


def test_the_unexpected_stop_time_reported_is_the_first_in_file_order():
    """Upstream reports `stopTimes.get(0)`, and the container is in file order, so a station
    named by three stop times reports the earliest row."""
    tables = dict(TABLES)
    tables["stop_times.txt"] = [
        stop_time(2, "T1", "ST1", 1),
        stop_time(3, "T1", "ST1", 2),
        stop_time(4, "T1", "ST1", 3),
    ]
    got = fire("location_with_unexpected_stop_time", tables)
    assert [row["stopTimeCsvRowNumber"] for row in got] == [2]


@pytest.mark.parametrize(
    ("code", "failed"),
    [
        ("unused_trip", "stop_times.txt"),
        ("unused_trip", "trips.txt"),
        ("unsorted_stop_times", "stop_times.txt"),
        ("stop_without_stop_time", "stop_times.txt"),
        ("stop_without_stop_time", "location_group_stops.txt"),
        ("location_with_unexpected_stop_time", "stop_times.txt"),
        ("location_with_unexpected_stop_time", "location_group_stops.txt"),
    ],
)
def test_a_failed_dependency_silences_the_rule(code, failed):
    """Upstream skips a FileValidator whose injected container has a non-parsable status.

    Measured three ways: with stop_times.txt absent, with one of its rows missing the
    required stop_sequence, and with a location_group_stops.txt whose second row leaves
    stop_id blank. The jar reports none of these notices in any of the three, while reading
    the failed table as simply empty reported every trip and every stop.
    """
    registry.load_rules()
    feed = FakeFeed(TABLES, unindexable=frozenset({failed}))
    assert list(registry.FILE_REGISTRY[code].func(feed, CTX)) == []


def test_a_valid_but_empty_stop_times_still_reports():
    """The gate is on table status, not on emptiness: a header-only stop_times.txt is a
    valid empty table, and the jar reports every trip unused and every stop unserved.
    Measured on a feed whose stop_times.txt is just its header."""
    tables = dict(TABLES)
    tables["stop_times.txt"] = []
    assert [row["tripId"] for row in fire("unused_trip", tables)] == [f"T{n}" for n in range(1, 7)]
    assert len(fire("stop_without_stop_time", tables)) == 4


def test_the_sample_cap_keeps_the_jars_thousand():
    """Above 1,000 notices of one code, iteration order decides which are kept.

    Measured on a feed with 1,005 unsorted trips: the jar reports totalNotices 1005 and its
    samples begin T0714, T0956, T0715, which is HashMap order over the trip ids. Emitting in
    file order kept T0000 onwards, a different thousand that no sorting can reconcile.
    """
    from gtfs_validator.javahash import hashmap_order

    ids = [f"T{index:04d}" for index in range(1005)]
    assert hashmap_order(ids)[:5] == ["T0714", "T0956", "T0715", "T0957", "T0712"]

    tables = {
        "stop_times.txt": [
            row
            for index, trip_id in enumerate(ids)
            for row in (
                stop_time(2 + index * 2, trip_id, "S1", 2),
                stop_time(3 + index * 2, trip_id, "S2", 1),
            )
        ]
    }
    reported = [row["tripId"] for row in fire("unsorted_stop_times", tables)]
    assert len(reported) == 1005
    assert reported[:5] == ["T0714", "T0956", "T0715", "T0957", "T0712"]
