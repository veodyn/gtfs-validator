"""block_trips_with_overlapping_stop_times, measured on the `block1` probe.

Nine blocks, one per branch of `BlockTripsWithOverlappingStopTimesValidator`. Every expectation
here is the jar's output on that feed, which reports five notices: one from B1, three from B6
and one from B7, and nothing from the six blocks built to be silent.

The two ways a pair is passed over are the interesting part and they are not the same test. The
loop **breaks** out of a trip when the next trip starts at or after this one ends, and it
**skips** one pair when the two trips share an exact arrival/departure handover, which is how
agencies model a block transfer. A feed can only tell them apart with three trips, since a
break also ends the comparisons a skip would have gone on to make.
"""

from __future__ import annotations

import pytest

from blockoverlap import (
    CODE,
    H8,
    H9,
    H10,
    H11,
    H12,
    MINUTE,
    calendar,
    fire,
    pairs,
    stop_times,
    trip,
)
from gtfs_validator.notices import Severity
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import DependencyFailed


def test_an_overlapping_pair_names_every_field_the_jar_does():
    """block1 B1, trips.txt rows 2 and 3: 08:00-09:00 against 08:30-09:30 on one service.

    The whole context in Gson's field order. `blockId` comes from the *first* trip of the pair,
    and `intersection` is the first date both services run, which for a Monday-to-Friday
    service starting on a Monday is the start date itself.
    """
    assert fire(
        [trip(2, "TA1"), trip(3, "TA2")],
        stop_times("TA1", (H8, H8), (H9, H9), first_row=2)
        + stop_times(
            "TA2",
            (H8 + 30 * MINUTE, H8 + 30 * MINUTE),
            (H9 + 30 * MINUTE, H9 + 30 * MINUTE),
            first_row=4,
        ),
    ) == [
        {
            "csvRowNumberA": 2,
            "tripIdA": "TA1",
            "serviceIdA": "WEEK",
            "csvRowNumberB": 3,
            "tripIdB": "TA2",
            "serviceIdB": "WEEK",
            "blockId": "B1",
            "intersection": "20260601",
        }
    ]


def test_an_exact_handover_is_allowed():
    """block1 B2: TB1 ends 09:00/09:10 and TB2 starts 09:00/09:10, so the pair is skipped.

    Both the arrival *and* the departure have to match. The trips still overlap on the clock,
    since TB2 begins before TB1's departure, so nothing but this exemption keeps the jar quiet.
    """
    times = stop_times("TB1", (H8, H8), (H9, H9 + 10 * MINUTE), first_row=2)
    times += stop_times("TB2", (H9, H9 + 10 * MINUTE), (H10, H10), first_row=4)
    assert fire([trip(2, "TB1", "B2"), trip(3, "TB2", "B2")], times) == []


def test_a_handover_matching_on_arrival_alone_is_still_an_overlap():
    """The exemption needs both fields, and one of the two is what a plain reading would test.

    Not in the probe, because the jar cannot show a *negative* of an exemption on a feed built
    for the positive: this is the same shape with TB2's departure moved by a minute, which the
    `and` in upstream's condition makes a notice.
    """
    times = stop_times("TB1", (H8, H8), (H9, H9 + 10 * MINUTE), first_row=2)
    times += stop_times("TB2", (H9, H9 + 11 * MINUTE), (H10, H10), first_row=4)
    assert pairs(fire([trip(2, "TB1", "B2"), trip(3, "TB2", "B2")], times)) == [("TB1", "TB2")]


def test_trips_that_merely_touch_do_not_overlap():
    """block1 B3: TC1 ends at 09:00 and TC2 starts at 09:00, which ends the search.

    The comparison is `<=`, so meeting exactly is not overlapping. This is the pair that would
    also be caught by the handover exemption, which is why B2 needs its own block.
    """
    times = stop_times("TC1", (H8, H8), (H9, H9), first_row=2)
    times += stop_times("TC2", (H9, H9), (H10, H10), first_row=4)
    assert fire([trip(2, "TC1", "B3"), trip(3, "TC2", "B3")], times) == []


def test_overlapping_trips_on_disjoint_services_are_silent():
    """block1 B4: the times overlap and the services never run on the same day."""
    times = stop_times("TD1", (H8, H8), (H9, H9), first_row=2)
    times += stop_times(
        "TD2",
        (H8 + 30 * MINUTE, H8 + 30 * MINUTE),
        (H9 + 30 * MINUTE, H9 + 30 * MINUTE),
        first_row=4,
    )
    monday = calendar("MON", tuesday=0, wednesday=0, thursday=0, friday=0)
    tuesday = calendar("TUE", monday=0, wednesday=0, thursday=0, friday=0)
    tuesday["_row_number"] = 3
    notices = fire(
        [trip(2, "TD1", "B4", "MON"), trip(3, "TD2", "B4", "TUE")],
        times,
        calendars=[monday, tuesday],
    )
    assert notices == []


def test_two_different_services_sharing_a_day_still_report():
    """The intersection is about *dates*, not about the service ids being equal.

    Every other positive case here puts both trips on one service, so a rule that asked
    `service_a == service_b` would pass all of them. These two run different services that share
    a weekday, and the notice carries a different `serviceIdA` and `serviceIdB`.
    """
    times = stop_times("TM1", (H8, H8), (H9, H9), first_row=2)
    times += stop_times(
        "TM2",
        (H8 + 30 * MINUTE, H8 + 30 * MINUTE),
        (H9 + 30 * MINUTE, H9 + 30 * MINUTE),
        first_row=4,
    )
    weekdays = calendar("WEEK")
    # Mondays only, which the Monday-to-Friday service also runs.
    mondays = calendar("MON", tuesday=0, wednesday=0, thursday=0, friday=0)
    mondays["_row_number"] = 3
    notices = fire(
        [trip(2, "TM1", "B9", "WEEK"), trip(3, "TM2", "B9", "MON")],
        times,
        calendars=[weekdays, mondays],
    )
    assert [(n["serviceIdA"], n["serviceIdB"], n["intersection"]) for n in notices] == [
        ("WEEK", "MON", "20260601")
    ]


def test_a_trip_missing_an_edge_time_leaves_the_comparison_entirely():
    """block1 B5: TE1's first stop time has an arrival and no departure.

    All four of first-arrival, first-departure, last-arrival and last-departure are required,
    and one absent field drops the whole *trip* rather than being defaulted. What distinguishes
    the two models is only whether the trip has an interval at all: TE1's span is decided by its
    first arrival and last departure, both of which are set, so defaulting the missing departure
    would leave the span at 08:00 to 09:00 and still overlap TE2. Including the trip is what
    produces a notice; excluding it is what the jar does.
    """
    times = stop_times("TE1", (H8, None), (H9, H9), first_row=2)
    times += stop_times(
        "TE2",
        (H8 + 30 * MINUTE, H8 + 30 * MINUTE),
        (H9 + 30 * MINUTE, H9 + 30 * MINUTE),
        first_row=4,
    )
    assert fire([trip(2, "TE1", "B5"), trip(3, "TE2", "B5")], times) == []


def test_a_trip_with_no_stop_times_is_not_an_interval():
    """block1 B8: TI1 has no rows at all, so the block has one interval and no pair."""
    times = stop_times("TI2", (H8, H8), (H9, H9), first_row=2)
    assert fire([trip(2, "TI1", "B8"), trip(3, "TI2", "B8")], times) == []


def test_three_overlapping_trips_report_every_pair():
    """block1 B6: TF1 08:00-11:00, TF2 09:00-11:30, TF3 10:00-12:00.

    Three pairs, in the order the nested loop produces them. This is also the block that shows
    the scan is every later trip rather than the adjacent one: TF1 against TF3 is reported even
    though TF2 sits between them.
    """
    times = stop_times("TF1", (H8, H8), (H11, H11), first_row=2)
    times += stop_times("TF2", (H9, H9), (H11 + 30 * MINUTE, H11 + 30 * MINUTE), first_row=4)
    times += stop_times("TF3", (H10, H10), (H12, H12), first_row=6)
    trips = [trip(2, "TF1", "B6"), trip(3, "TF2", "B6"), trip(4, "TF3", "B6")]
    assert pairs(fire(trips, times)) == [("TF1", "TF2"), ("TF1", "TF3"), ("TF2", "TF3")]


def test_the_pair_is_ordered_by_first_arrival_and_not_by_file_order():
    """block1 B7, whose two trips are written later-first: the jar names row 16 before row 15.

    The intervals are sorted by first arrival, so TG2 becomes the A of the pair despite being
    the second row of the file. Reading file order would have swapped every field in the
    notice, and a probe whose trips happen to be written in time order cannot tell.
    """
    times = stop_times("TG1", (H9, H9), (H10 + 30 * MINUTE, H10 + 30 * MINUTE), first_row=2)
    times += stop_times("TG2", (H8, H8), (H9 + 30 * MINUTE, H9 + 30 * MINUTE), first_row=4)
    notices = fire([trip(15, "TG1", "B7"), trip(16, "TG2", "B7")], times)
    assert [(n["csvRowNumberA"], n["csvRowNumberB"]) for n in notices] == [(16, 15)]


def _overlapping_pair():
    """Two trips whose spans overlap by half an hour, for the block-id presence pair below."""
    times = stop_times("TH1", (H8, H8), (H9, H9), first_row=2)
    times += stop_times(
        "TH2",
        (H8 + 30 * MINUTE, H8 + 30 * MINUTE),
        (H9 + 30 * MINUTE, H9 + 30 * MINUTE),
        first_row=4,
    )
    return times


def test_trips_without_a_block_id_are_never_compared():
    """block1's two block-less trips overlap and draw nothing.

    They are still a group: the container keys them under the type default, so the rule has to
    ask whether the *first* member has a block id rather than assume the key is absent.

    None here, not `""`. This test used to pass `""` and assert silence, which pinned the wrong
    behaviour; see the pair below.
    """
    assert fire([trip(2, "TH1", None), trip(3, "TH2", None)], _overlapping_pair()) == []


def test_a_block_id_that_is_present_but_empty_is_still_a_block():
    """Measured on the `ws3` probe: the jar reports the pair with `blockId: ""`.

    `hasBlockId()` asks whether the column carried a value, not whether that value is non-empty,
    and a cell of `" "` is trimmed to `""` while staying present. So two trips whose block_id is a
    single space are in one block and are compared, where two trips with no block_id at all are
    not. Truthiness cannot tell those apart and silently skipped both, which is a notice the jar
    emits and we did not.
    """
    got = fire([trip(2, "TH1", ""), trip(3, "TH2", "")], _overlapping_pair())
    assert [(row["tripIdA"], row["tripIdB"], row["blockId"]) for row in got] == [("TH1", "TH2", "")]


def test_blocks_come_out_in_multimap_order():
    """The groups are a Guava multimap's values, so the block ids decide the order.

    **B6 is written before B1**, which is the whole point. In file order this feed's blocks are
    B6 then B1; the multimap yields B1 then B6, and the notices come out that way. An earlier
    version of this test put B1 first, where the two orders agree, so a rule iterating a plain
    dict of blocks passed it. A test whose subject is an ordering has to be given an input whose
    orderings differ.
    """
    times = stop_times("TF1", (H8, H8), (H11, H11), first_row=2)
    times += stop_times("TF2", (H9, H9), (H11 + 30 * MINUTE, H11 + 30 * MINUTE), first_row=4)
    times += stop_times("TA1", (H8, H8), (H9, H9), first_row=6)
    times += stop_times(
        "TA2",
        (H8 + 30 * MINUTE, H8 + 30 * MINUTE),
        (H9 + 30 * MINUTE, H9 + 30 * MINUTE),
        first_row=8,
    )
    trips = [
        trip(2, "TF1", "B6"),
        trip(3, "TF2", "B6"),
        trip(4, "TA1", "B1"),
        trip(5, "TA2", "B1"),
    ]
    assert [n["blockId"] for n in fire(trips, times)] == ["B1", "B6"]


def test_the_code_is_registered_as_an_error():
    registry.load_rules()
    assert registry.FILE_REGISTRY[CODE].severity is Severity.ERROR


@pytest.mark.parametrize(
    "table", ["trips.txt", "stop_times.txt", "calendar.txt", "calendar_dates.txt"]
)
def test_any_injected_table_failing_silences_the_rule(table):
    """All four injected containers, so any one of them failing gates the whole validator.

    `calendar_dates.txt` was missing from this list while the docstring claimed four, which is a
    rule that never read the exceptions passing a test named for reading them.
    """
    times = stop_times("TA1", (H8, H8), (H9, H9), first_row=2)
    times += stop_times(
        "TA2",
        (H8 + 30 * MINUTE, H8 + 30 * MINUTE),
        (H9 + 30 * MINUTE, H9 + 30 * MINUTE),
        first_row=4,
    )
    with pytest.raises(DependencyFailed):
        fire([trip(2, "TA1"), trip(3, "TA2")], times, unindexable=frozenset({table}))
