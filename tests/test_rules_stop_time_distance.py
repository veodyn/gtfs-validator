"""StopTimeIncreasingDistanceValidator: one code, and three ways a row leaves the scan.

Probe feeds, both built by `make_sdist_probes.py`:

- `sdist`, eight trips of three stop times each: increasing, decreasing, equal, a middle row
  with no stop_id, a first row with no distance, one whose file order disagrees with its
  stop_sequence, the no-stop_id case again with a location named instead, and a *middle* row
  with no distance. The jar reports five notices.
- `sdistgate`, the same rows with the `shape_dist_traveled` column dropped, which reports
  none.

The two skips look alike in the Java and are not the same. A row with no stop_id `continue`s
*before* the assignment that advances `prev`, so the comparison spans it. A row whose
distance is unset fails the comparison but still becomes `prev`. `sdist`'s T4, T7 and T8 are
built to tell those apart: T4 and T7 would report a notice if the skipped row advanced `prev`,
and T8 would report one if the unset row did not. A review found the first version of this
file asserting the distinction with T5, whose `unset, 5, 1` gives the same answer under either
model; T8's `5, unset, 1` is what actually discriminates.
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

CODE = "decreasing_or_equal_stop_time_distance"
STOP_TIMES = "stop_times.txt"


def stop_time(number, trip_id, sequence, *, stop_id="S1", distance=None):
    """One stop_times row, with both gate columns present unless a test drops them."""
    return {
        "_row_number": number,
        "trip_id": trip_id,
        "stop_id": stop_id,
        "stop_sequence": sequence,
        "shape_dist_traveled": distance,
    }


def fire(rows, unindexable=frozenset()):
    registry.load_rules()
    feed = FakeFeed({STOP_TIMES: rows}, unindexable=unindexable)
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(feed, CTX)]


def test_increasing_distances_draw_nothing():
    """sdist T1, rows 2 to 4: 0, 1.25, 2.5."""
    rows = [
        stop_time(2, "T1", 1, stop_id="S1", distance=0),
        stop_time(3, "T1", 2, stop_id="S2", distance=1.25),
        stop_time(4, "T1", 3, stop_id="S3", distance=2.5),
    ]
    assert fire(rows) == []


def test_a_decreasing_distance_names_both_rows():
    """sdist T2, rows 5 to 7, whose third row goes back from 2.5 to 1.25.

    Every key and value here is the jar's, including the field order Gson wrote them in.
    """
    rows = [
        stop_time(5, "T2", 1, stop_id="S1", distance=0),
        stop_time(6, "T2", 2, stop_id="S2", distance=2.5),
        stop_time(7, "T2", 3, stop_id="S3", distance=1.25),
    ]
    assert fire(rows) == [
        {
            "tripId": "T2",
            "stopId": "S3",
            "csvRowNumber": 7,
            "shapeDistTraveled": 1.25,
            "stopSequence": 3,
            "prevCsvRowNumber": 6,
            "prevShapeDistTraveled": 2.5,
            "prevStopSequence": 2,
        }
    ]


def test_an_equal_distance_is_an_error_too():
    """sdist T3, rows 8 to 10. The comparison is `>=`, so standing still counts."""
    rows = [
        stop_time(8, "T3", 1, stop_id="S1", distance=0),
        stop_time(9, "T3", 2, stop_id="S2", distance=2.5),
        stop_time(10, "T3", 3, stop_id="S3", distance=2.5),
    ]
    assert [row["csvRowNumber"] for row in fire(rows)] == [10]


@pytest.mark.parametrize(
    ("trip_id", "numbers"),
    [("T4", (11, 12, 13)), ("T7", (20, 21, 22))],
)
def test_a_row_without_a_stop_id_does_not_become_the_previous_row(trip_id, numbers):
    """sdist T4 and T7, both distances 0, 100, 0.5 with no stop_id on the middle row.

    The jar reports nothing for either. Upstream skips such a row before assigning `prev`, so
    0.5 is compared against 0 and is an increase; advancing `prev` over it would compare
    against 100 and emit a notice the jar does not.

    T7 is here because T4 alone does not settle it. T4's middle row draws
    `missing_required_field`, so "the rule skipped it" and "the loader never stored it" both
    predict silence. T7's middle row names a location instead, which satisfies the
    conditional requirement, and the jar's `forbidden_shape_dist_traveled` on that very row
    proves a validator saw it. The row is stored and still does not become `prev`.
    """
    first, middle, last = numbers
    rows = [
        stop_time(first, trip_id, 1, stop_id="S1", distance=0),
        stop_time(middle, trip_id, 2, stop_id=None, distance=100),
        stop_time(last, trip_id, 3, stop_id="S3", distance=0.5),
    ]
    assert fire(rows) == []


def test_a_row_without_a_distance_still_becomes_the_previous_row():
    """sdist T8, rows 23 to 25: 5, then no distance, then 1. The jar reports nothing.

    This is the case that separates the two skips, and T5 below does not. The unset row
    becomes `prev`, so 1 is compared against an absence and nothing is reported. A rule that
    skipped it the way it skips a row with no stop_id would leave `prev` at 5, compare 5
    against 1, and emit a notice the jar does not.
    """
    rows = [
        stop_time(23, "T8", 1, stop_id="S1", distance=5),
        stop_time(24, "T8", 2, stop_id="S2", distance=None),
        stop_time(25, "T8", 3, stop_id="S3", distance=1),
    ]
    assert fire(rows) == []


def test_a_pair_after_an_unset_distance_is_still_compared():
    """sdist T5, rows 14 to 16: no distance, then 5, then 1.

    One notice, rows 15 and 16. Weaker than the test above, which is the point of keeping
    both: this one passes whether or not the unset row advances `prev`, because the notice it
    checks comes from the two rows after it. It pins the *count*, that a leading unset
    distance does not suppress the rest of the trip.
    """
    rows = [
        stop_time(14, "T5", 1, stop_id="S1", distance=None),
        stop_time(15, "T5", 2, stop_id="S2", distance=5),
        stop_time(16, "T5", 3, stop_id="S3", distance=1),
    ]
    assert [(row["prevCsvRowNumber"], row["csvRowNumber"]) for row in fire(rows)] == [(15, 16)]


def test_rows_are_compared_in_stop_sequence_order_not_file_order():
    """sdist T6, rows 17 to 19, written as sequence 3, 1, 2 with distances 1, 10, 5.

    The container indexes stop times by (trip_id, stop_sequence), so the scan sees 10, 5, 1
    and reports two decreases. File order would see 1, 10, 5 and report one, naming the
    wrong rows.
    """
    rows = [
        stop_time(17, "T6", 3, stop_id="S3", distance=1),
        stop_time(18, "T6", 1, stop_id="S1", distance=10),
        stop_time(19, "T6", 2, stop_id="S2", distance=5),
    ]
    assert [(row["prevCsvRowNumber"], row["csvRowNumber"]) for row in fire(rows)] == [
        (18, 19),
        (19, 17),
    ]


def test_the_trips_come_out_in_multimap_order():
    """sdist's five notices arrive T5, T6, T6, T2, T3, which is not file order.

    Upstream iterates `Multimaps.asMap(stopTimeTable.byTripIdMap())`, whose 32-bucket table
    yields T4, T5, T6, T7, T8, T1, T2, T3 for the probe's eight ids. T4, T7, T8 and T1 draw
    nothing, leaving exactly the jar's sequence.
    """
    rows = [
        stop_time(5, "T2", 1, stop_id="S1", distance=2),
        stop_time(6, "T2", 2, stop_id="S2", distance=1),
        stop_time(8, "T3", 1, stop_id="S1", distance=2),
        stop_time(9, "T3", 2, stop_id="S2", distance=1),
        stop_time(15, "T5", 1, stop_id="S1", distance=2),
        stop_time(16, "T5", 2, stop_id="S2", distance=1),
        stop_time(18, "T6", 1, stop_id="S1", distance=2),
        stop_time(19, "T6", 2, stop_id="S2", distance=1),
    ]
    assert [row["tripId"] for row in fire(rows)] == ["T5", "T6", "T2", "T3"]


@pytest.mark.parametrize("column", ["stop_id", "shape_dist_traveled"])
def test_the_rule_is_gated_on_both_columns(column):
    """sdistgate drops `shape_dist_traveled` and reports nothing.

    `shouldCallValidate` tests both columns, and only one of the two is observable: with no
    `stop_id` column every row fails `hasStopId` and is skipped anyway, so that conjunct is
    modelled for fidelity rather than for an effect a feed can show. Dropping them one at a
    time is what keeps this from passing against a gate that tests only one.
    """
    rows = [
        stop_time(5, "T2", 1, stop_id="S1", distance=2),
        stop_time(6, "T2", 2, stop_id="S2", distance=1),
    ]
    for row in rows:
        del row[column]
    assert fire(rows) == []


def test_a_failed_stop_times_load_silences_the_rule():
    """The validator takes only the stop_time container, so its failure is the whole gate.

    The rows are here to get past the column gate: `has_column` reads the header a failed
    load still recorded, so reaching `rows()` is what the engine relies on to discard the
    rule's output.
    """
    rows = [stop_time(5, "T2", 1, stop_id="S1", distance=2)]
    with pytest.raises(DependencyFailed):
        fire(rows, unindexable=frozenset({STOP_TIMES}))


def test_the_code_is_registered_as_an_error():
    registry.load_rules()
    assert registry.FILE_REGISTRY[CODE].severity is Severity.ERROR
