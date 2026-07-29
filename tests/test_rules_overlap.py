"""OverlappingFrequencyValidator and TimeframeOverlapValidator, one code each.

The same shape twice: group the rows, sort each group, compare adjacent pairs, and report
where the later one starts before the earlier one ends. What differs is the grouping key, the
third sort key, and the order the *groups* come out in, and all three are measured.

Probe feeds:

- `freqov`, eleven frequencies rows: a touching pair, a plain overlap, a long window
  containing a short one plus a third overlapping only the long one, two identical rows, and
  a pair whose headways are in descending order;
- `freqorder`, three trips whose ids the multimap yields in an order that is not file order;
- `tfov`, ten timeframes rows: an overlap, the same times under another service and another
  group, a touching pair, two rows with no group id, and two rows with no times at all.

The group order is the part a plain reading gets wrong. `freqorder`'s trips are written
T1, T2, T4 and reported T4, T1, T2, which is what `ArrayListMultimap`'s 32-bucket table
yields. `tfov` reports the empty-group overlap *before* the G1 overlap, which is what a
`groupingBy` table yields for `@AutoValue` keys whose hashCode folds the two components.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.notices import Severity
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import DependencyFailed

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")

FREQUENCY = "overlapping_frequency"
TIMEFRAME = "timeframe_overlap"
FREQUENCIES = "frequencies.txt"
TIMEFRAMES = "timeframes.txt"

T0800, T0900, T1000, T1100, T1200, T1300 = 28800, 32400, 36000, 39600, 43200, 46800


def frequency(number, trip_id, start, end, headway=600):
    return {
        "_row_number": number,
        "trip_id": trip_id,
        "start_time": start,
        "end_time": end,
        "headway_secs": headway,
    }


def timeframe(number, group_id, start, end, service_id="WEEK"):
    return {
        "_row_number": number,
        "timeframe_group_id": group_id,
        "start_time": start,
        "end_time": end,
        "service_id": service_id,
    }


def fire(code, filename, rows, unindexable=frozenset()):
    registry.load_rules()
    feed = FakeFeed({filename: rows}, unindexable=unindexable)
    return [notice.context for notice in registry.FILE_REGISTRY[code].func(feed, CTX)]


def frequencies(rows):
    return fire(FREQUENCY, FREQUENCIES, rows)


def timeframes(rows):
    return fire(TIMEFRAME, TIMEFRAMES, rows)


# --- overlapping_frequency ----------------------------------------------------------------


def test_windows_that_touch_do_not_overlap():
    """freqov rows 2 and 3: 08:00 to 09:00 then 09:00 to 10:00 draws nothing. The test is
    `curr.start < prev.end`, strictly, so a window may begin exactly where one ends."""
    rows = [frequency(2, "TA", T0800, T0900), frequency(3, "TA", T0900, T1000)]
    assert frequencies(rows) == []


def test_a_plain_overlap_names_both_rows():
    """freqov rows 4 and 5."""
    rows = [frequency(4, "TB", T0800, T1000), frequency(5, "TB", T0900, T1100)]
    assert frequencies(rows) == [
        {
            "prevCsvRowNumber": 4,
            "prevEndTime": "10:00:00",
            "currCsvRowNumber": 5,
            "currStartTime": "09:00:00",
            "tripId": "TB",
        }
    ]


def test_only_adjacent_pairs_are_compared():
    """freqov rows 6, 7 and 8: 08:00-12:00, 09:00-10:00, 11:00-13:00.

    The third window overlaps the first and the jar reports it once, not twice: the scan
    compares each row with the one before it after sorting, so 11:00-13:00 is only ever
    checked against 09:00-10:00, which it does not overlap. Comparing every pair would report
    a second notice the jar does not.
    """
    rows = [
        frequency(6, "TC", T0800, T1200),
        frequency(7, "TC", T0900, T1000),
        frequency(8, "TC", T1100, T1300),
    ]
    assert frequencies(rows) == [
        {
            "prevCsvRowNumber": 6,
            "prevEndTime": "12:00:00",
            "currCsvRowNumber": 7,
            "currStartTime": "09:00:00",
            "tripId": "TC",
        }
    ]


def test_two_identical_windows_overlap():
    """freqov rows 9 and 10. A window overlaps its own duplicate, since the start is before
    the end rather than equal to it."""
    rows = [frequency(9, "TD", T0800, T0900), frequency(10, "TD", T0800, T0900)]
    assert [row["prevCsvRowNumber"] for row in frequencies(rows)] == [9]


def test_the_headway_is_the_third_sort_key():
    """freqov rows 11 and 12, whose windows are identical and whose headways are 900 then 300.

    The jar reports row **12** as prev. Sorting on start and end alone would leave file order
    and report row 11, so this is the one case in the probe that pins the third key.
    """
    rows = [
        frequency(11, "TE", T0800, T1000, headway=900),
        frequency(12, "TE", T0800, T1000, headway=300),
    ]
    assert frequencies(rows) == [
        {
            "prevCsvRowNumber": 12,
            "prevEndTime": "10:00:00",
            "currCsvRowNumber": 11,
            "currStartTime": "08:00:00",
            "tripId": "TE",
        }
    ]


def test_two_trips_do_not_overlap_each_other():
    """Windows overlap only within a trip, which is what the grouping is for."""
    rows = [frequency(2, "TA", T0800, T1000), frequency(3, "TB", T0900, T1100)]
    assert frequencies(rows) == []


def test_trips_come_out_in_multimap_order():
    """freqorder: three trips written T1, T2, T4 and reported T4, T1, T2.

    `byTripIdMap()` is an `ArrayListMultimap`, whose backing table starts at 32 buckets rather
    than a `HashMap`'s 16, and iterating it is what decides which notices survive the
    1,000-sample cap. File order would have reported T1 first, and the differential harness
    cannot see the difference because it compares samples as a sorted multiset.
    """
    rows = []
    for number, trip_id in enumerate(["T1", "T2", "T4"]):
        rows.append(frequency(2 + number * 2, trip_id, T0800, T1000))
        rows.append(frequency(3 + number * 2, trip_id, T0900, T1100))
    assert [row["tripId"] for row in frequencies(rows)] == ["T4", "T1", "T2"]


def test_a_failed_frequencies_table_silences_the_rule():
    rows = [frequency(2, "TB", T0800, T1000), frequency(3, "TB", T0900, T1100)]
    with pytest.raises(DependencyFailed):
        fire(FREQUENCY, FREQUENCIES, rows, unindexable=frozenset({FREQUENCIES}))


# --- timeframe_overlap --------------------------------------------------------------------


def test_a_timeframe_overlap_names_its_group_and_service():
    """tfov rows 2 and 3."""
    rows = [timeframe(2, "G1", T0800, T1000), timeframe(3, "G1", T0900, T1100)]
    assert timeframes(rows) == [
        {
            "prevCsvRowNumber": 2,
            "prevEndTime": "10:00:00",
            "currCsvRowNumber": 3,
            "currStartTime": "09:00:00",
            "timeframeGroupId": "G1",
            "serviceId": "WEEK",
        }
    ]


def test_the_same_times_under_another_service_do_not_overlap():
    """tfov row 4: the key is the group *and* the service, so a weekend timeframe may cover
    the same hours as a weekday one."""
    rows = [timeframe(2, "G1", T0800, T1000), timeframe(4, "G1", T0900, T1100, "WKND")]
    assert timeframes(rows) == []


def test_the_same_times_under_another_group_do_not_overlap():
    """tfov row 7."""
    rows = [timeframe(2, "G1", T0800, T1000), timeframe(7, "G3", T0900, T1100)]
    assert timeframes(rows) == []


def test_timeframes_that_touch_do_not_overlap():
    """tfov rows 5 and 6."""
    rows = [timeframe(5, "G2", T0800, T0900), timeframe(6, "G2", T0900, T1000)]
    assert timeframes(rows) == []


def test_rows_without_a_group_id_group_together_under_the_empty_default():
    """tfov rows 8 and 9, which leave timeframe_group_id blank and still overlap each other.

    `timeframe_group_id` is optional, and an unset one is not an absence: the getter returns
    the empty string, both rows land in the same group, and the notice carries `""`. Treating
    the unset column as its own group per row, or skipping such rows, loses this notice.
    """
    rows = [timeframe(8, None, T0800, T1000), timeframe(9, None, T0900, T1100)]
    assert timeframes(rows) == [
        {
            "prevCsvRowNumber": 8,
            "prevEndTime": "10:00:00",
            "currCsvRowNumber": 9,
            "currStartTime": "09:00:00",
            "timeframeGroupId": "",
            "serviceId": "WEEK",
        }
    ]


def test_rows_without_times_do_not_overlap():
    """tfov rows 10 and 11, which leave both times blank.

    Both read as `GtfsTime`'s zero, so the test is 00:00:00 < 00:00:00, which is false. The
    rows are a group of two identical zero-length windows and the jar reports nothing. Reading
    an unset time as an absence and skipping the row gives the same answer here by accident;
    reading it as anything but zero does not.
    """
    rows = [timeframe(10, "G4", None, None), timeframe(11, "G4", None, None)]
    assert timeframes(rows) == []


def test_groups_come_out_in_grouping_by_order():
    """tfov: the empty-group overlap is reported *before* the G1 overlap, although G1's rows
    come first in the file.

    `Collectors.groupingBy` builds a `HashMap` keyed by an `@AutoValue` pair whose hashCode
    folds the two components, and iterating it is what decides which notices survive the
    1,000-sample cap. This is the assertion that pins the fold: with the components hashed in
    the other order, or the fold's seed wrong, the two notices come out the other way round.
    """
    rows = [
        timeframe(2, "G1", T0800, T1000),
        timeframe(3, "G1", T0900, T1100),
        timeframe(8, None, T0800, T1000),
        timeframe(9, None, T0900, T1100),
    ]
    assert [row["timeframeGroupId"] for row in timeframes(rows)] == ["", "G1"]


def test_a_failed_timeframes_table_silences_the_rule():
    rows = [timeframe(2, "G1", T0800, T1000), timeframe(3, "G1", T0900, T1100)]
    with pytest.raises(DependencyFailed):
        fire(TIMEFRAME, TIMEFRAMES, rows, unindexable=frozenset({TIMEFRAMES}))


@pytest.mark.parametrize("code", [FREQUENCY, TIMEFRAME])
def test_both_codes_are_errors(code):
    registry.load_rules()
    assert registry.FILE_REGISTRY[code].severity is Severity.ERROR
