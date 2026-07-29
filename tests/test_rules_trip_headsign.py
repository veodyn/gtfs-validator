"""TripHeadsignValidator: which trips and stops the scan visits, and when it stops.

Every expectation was measured on the jar rather than read off the Java, because two of this
validator's behaviours are bugs that a plain reading of its intent would not predict. Both are
pinned below, and both are upstream's behaviour rather than a divergence: reproducing them is the
point. The probe feeds are `headsign1`, `headsign2` and `headsign3`.

What counts as a *present* headsign or stop name, and what the notice carries, is next door in
`test_rules_trip_headsign_presence`. The split is by responsibility rather than by size: this half
is control flow, that half is field semantics, and the field semantics turned out to be where the
first version of this rule was wrong.
"""

from __future__ import annotations

from headsignfeed import STOPS, fire, stop, stop_times, trip


def test_a_headsign_naming_an_intermediate_stop_reports_six_fields():
    """Measured on `headsign1`, trip T1: the headsign is the *first* stop's name.

    "Intermediate" in upstream's sense is every stop but the last, so the first stop counts. The
    six fields and their order are Gson's, from the notice class's field declarations; the order
    itself is pinned in the presence module, since dict equality here cannot see it.
    """
    got = fire([trip(2, "T1", "Alpha")], stop_times("T1", "A", "B", "C"))
    assert got == [
        {
            "csvRowNumber": 2,
            "tripId": "T1",
            "tripHeadsign": "Alpha",
            "stopId1": "A",
            "stopSequence": 1,
            "stopId2": "C",
        }
    ]


def test_a_headsign_naming_the_last_stop_is_silent():
    """Measured on `headsign1`, trip T2: headsign "Gamma", last stop C named Gamma, no notice.

    This is the whole point of the check, so it is also the case most easily broken by an
    off-by-one in the loop bound.
    """
    assert fire([trip(3, "T2", "Gamma")], stop_times("T2", "A", "B", "C")) == []


def test_the_comparison_ignores_case():
    """Measured on `headsign1`, trip T3: "aLPHa" matches the stop named "Alpha".

    ASCII only, which is all this case establishes. That the fold is Java's rather than Python's
    is a separate test, because the two agree on every ASCII pair.
    """
    got = fire([trip(4, "T3", "aLPHa")], stop_times("T3", "A", "B", "C"))
    assert [row["tripHeadsign"] for row in got] == ["aLPHa"]


def test_one_trip_can_draw_a_notice_per_matching_stop():
    """Measured on `headsign3`, trip V3: two intermediate stops both named "Alpha", two notices.

    The inner loop has no break, so the notices are per stop time and not per trip.
    """
    got = fire(
        [trip(4, "V3", "Alpha")],
        stop_times("V3", "A", "A2", "C"),
        [*STOPS, stop("A2", "Alpha")],
    )
    assert [(row["stopId1"], row["stopSequence"]) for row in got] == [("A", 1), ("A2", 2)]


def test_a_circular_trip_silences_every_trip_after_it():
    """Upstream bug, measured on `headsign1`: T4 is circular and T5 then reports nothing.

    The circular test is `return`, not `continue`, so it abandons the *whole validator* rather
    than the trip. T5's headsign "Beta" names its own intermediate stop B and would otherwise
    draw a notice; on the jar it does not. T1 and T3, which come before T4, are unaffected,
    since their notices are already in the container.

    This is upstream's behaviour rather than a divergence, so it belongs here and in the rule's
    docstring rather than as a recorded divergence.
    """
    trips = [
        trip(2, "T1", "Alpha"),
        trip(5, "T4", "Alpha"),
        trip(6, "T5", "Beta"),
    ]
    times = [
        *stop_times("T1", "A", "B", "C"),
        *stop_times("T4", "A", "B", "A"),
        *stop_times("T5", "A", "B", "C"),
    ]
    assert [row["tripId"] for row in fire(trips, times)] == ["T1"]


def test_the_circular_test_compares_ids_that_are_not_short():
    """Also upstream: the circular test is `==` on two Strings rather than `equals`.

    Reference equality would depend on the loader sharing the id instances, which is not a thing
    a reader should assume. Measured on `headsign2`, whose circular trip U2 begins and ends at
    `LONGISH_STOP_IDENTIFIER_0001`: it still silences U3, so the instances are shared and `==`
    answers as equality would. A plain Python `==` is therefore the faithful port, and this test
    exists to record that the question was asked and settled by measurement.

    The two ids are deliberately **distinct objects** with equal values. Writing the same literal
    twice would have CPython hand back one interned object, and then a rule using `is` would pass
    this test too: the assertion would be about nothing. `"".join` builds a fresh string, and the
    premise is asserted rather than assumed, since it depends on an implementation detail of the
    interpreter that a future version is free to change. Confirmed by patching the rule to `is`
    and watching this fail.
    """
    first_id = "LONGISH_STOP_IDENTIFIER_0001"
    last_id = "".join(first_id)
    assert first_id == last_id and first_id is not last_id
    trips = [trip(2, "U1", "Alpha"), trip(3, "U2", "Delta"), trip(4, "U3", "Beta")]
    times = [
        *stop_times("U1", "A", "B", first_id),
        *stop_times("U2", first_id, "B", last_id),
        *stop_times("U3", "A", "B", "C"),
    ]
    stops = [*STOPS, stop(first_id, "Delta")]
    assert [row["tripId"] for row in fire(trips, times, stops)] == ["U1"]


def test_a_trip_with_no_headsign_is_skipped_before_the_circular_test():
    """Measured on `headsign3`, trip V1: absent headsign *and* circular, and V2 still reports.

    The order of the two guards is observable exactly here. If the headsign test came second, V1
    would hit the `return` and silence the rest of the feed. Note that this depends on the cell
    being *absent* rather than empty: the same trip with a whitespace-only headsign does silence
    the feed, which is the presence module's business.
    """
    trips = [trip(2, "V1", None), trip(3, "V2", "Beta")]
    times = [*stop_times("V1", "A", "B", "A"), *stop_times("V2", "A", "B", "C")]
    assert [row["tripId"] for row in fire(trips, times)] == ["V2"]


def test_a_trip_with_fewer_than_two_stop_times_is_skipped_and_the_scan_continues():
    """Measured on `headsign3`: V4 has one stop time, and V5 after it is still checked.

    `continue` here rather than `return`, which is the one guard in this validator that does what
    it looks like it does. A single stop time has no intermediate stop, and a trip with none is
    another rule's notice.
    """
    trips = [trip(5, "V4", "Alpha"), trip(6, "V5", "Beta")]
    times = [*stop_times("V4", "A"), *stop_times("V5", "A", "B", "C")]
    assert [row["tripId"] for row in fire(trips, times)] == ["V5"]


def test_a_stop_absent_from_stops_txt_matches_nothing():
    """`stopTable.byStopId` returns an Optional and the branch tests it.

    An unresolvable stop id is `foreign_key_violation`'s business, not this rule's, and reading
    it as a name of "" would make an empty headsign match it.
    """
    got = fire([trip(2, "T1", "Alpha")], stop_times("T1", "GHOST", "B", "C"), [stop("B", "Beta")])
    assert got == []


def test_a_stop_with_no_name_matches_nothing():
    """`hasStopName()` guards the comparison, so a nameless stop cannot match any headsign.

    None here is a stops.txt with the cell missing or empty. A stop whose name is present and
    empty is a different case and does match an empty headsign; see the presence module.
    """
    got = fire(
        [trip(2, "T1", "Alpha")],
        stop_times("T1", "N", "B", "C"),
        [stop("N", None), *STOPS],
    )
    assert got == []


def test_stop_times_are_read_in_stop_sequence_order_not_file_order():
    """`byTripId` is sorted by (trip_id, stop_sequence), so which stop is last is the sequence's.

    A feed whose rows are shuffled has the same first and last stop as one that is not. Written
    against the sequences rather than the row order: with the rows below taken as they come, the
    trip would look circular and silence itself.
    """
    rows = stop_times("T1", "A", "B", "C")
    shuffled = [rows[2], rows[0], rows[1]]
    got = fire([trip(2, "T1", "Alpha")], shuffled)
    assert [(row["stopId1"], row["stopSequence"], row["stopId2"]) for row in got] == [("A", 1, "C")]
