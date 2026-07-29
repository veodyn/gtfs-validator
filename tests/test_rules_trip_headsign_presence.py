"""TripHeadsignValidator: what counts as a present field, and what the notice carries.

Split from the control-flow half because this is where the first version of the rule was wrong, in
a way none of the other tests could see. It read presence as truthiness, which collapses two states
the store keeps apart:

- a missing or empty cell is `None`,
- a whitespace-only cell is `""`, because the loader trims it and still records a value,
- anything else is its trimmed text.

`hasTripHeadsign()` and `hasStopName()` are generated from whether the column had a value, so the
middle state is **present**. Both directions are measured on the jar: `whitespace1` for the
control-flow consequence, `whitespace2` for the notice.
"""

from __future__ import annotations

from gtfs_validator.manifest import load_manifest
from headsignfeed import CODE, STOPS, fire, stop, stop_times, trip


def test_the_context_keys_are_in_the_order_upstream_declares_them():
    """Dict equality cannot see key order, and nothing else in the project can either.

    `tools/diff_against_upstream.sh` serialises every sample with `sort_keys=True` before diffing,
    so a rule that emits Gson's fields in the wrong order matches the jar on every probe feed. The
    order therefore has to be pinned here, and against `canonical_notices.json` rather than against
    a list retyped from the Java: that file is generated from upstream at the pin, so a field
    reordered upstream fails this rather than silently agreeing with a stale copy.
    """
    got = fire([trip(2, "T1", "Alpha")], stop_times("T1", "A", "B", "C"))
    assert list(got[0]) == list(load_manifest().context_fields_of(CODE))


def test_the_row_number_and_sequence_are_integers_and_not_bools_or_floats():
    """Dict equality cannot see this either: Python holds `1 == 1.0 == True`.

    The report writer serialises whatever the context carries, so a float here would put `1.0` in
    the JSON where the jar puts `1`, and `True` would put `true`. Both are types the manifest
    declares as `integer`. `type(...) is int` rather than `isinstance`, because `bool` is a subclass
    of `int` and would pass an instance check.
    """
    got = fire([trip(2, "T1", "Alpha")], stop_times("T1", "A", "B", "C"))[0]
    declared = load_manifest().context_fields_of(CODE)
    for field, kind in declared.items():
        if kind == "integer":
            assert type(got[field]) is int, f"{field} is {type(got[field]).__name__}"
        else:
            assert type(got[field]) is str, f"{field} is {type(got[field]).__name__}"


def test_a_whitespace_only_headsign_is_present_and_matches_an_empty_stop_name():
    """Measured on `whitespace2`: a headsign of `" "` matches a stop named `" "`, notice included.

    This replaces a test that asserted the opposite and was wrong. The jar emits `tripHeadsign: ""`
    here, which the earlier reading of this rule could not produce at all: it skipped the trip.
    """
    got = fire([trip(2, "X1", "")], stop_times("X1", "N", "B", "C"), [stop("N", ""), *STOPS])
    assert got == [
        {
            "csvRowNumber": 2,
            "tripId": "X1",
            "tripHeadsign": "",
            "stopId1": "N",
            "stopSequence": 1,
            "stopId2": "C",
        }
    ]


def test_a_whitespace_only_headsign_still_triggers_the_circular_return():
    """Measured on `whitespace1`, and the reason the distinction matters beyond one notice.

    Its first trip has a headsign of `" "` and is circular, and the jar reports **nothing**: the
    trip counted as having a headsign, so it reached the circular test and returned from the whole
    validator. Reading `""` as absent skipped that trip and reported the one after it, a notice the
    jar does not emit. One space in one cell therefore decides whether the rest of the feed is
    checked at all, which is why truthiness was not a safe shorthand for presence.
    """
    trips = [trip(2, "W1", ""), trip(3, "W2", "Beta")]
    times = [*stop_times("W1", "A", "B", "A"), *stop_times("W2", "A", "B", "C")]
    assert fire(trips, times) == []


def test_an_absent_headsign_is_not_the_same_as_an_empty_one():
    """The pair that the truthiness reading collapsed, side by side on one feed shape.

    Same circular first trip, same reportable second trip, and the only difference is None against
    `""`. The jar reports V2 in the first case and nothing in the second, so any implementation that
    cannot tell the two cells apart gets one of them wrong whichever way it guesses.
    """
    times = [*stop_times("W1", "A", "B", "A"), *stop_times("W2", "A", "B", "C")]
    absent = [trip(2, "W1", None), trip(3, "W2", "Beta")]
    empty = [trip(2, "W1", ""), trip(3, "W2", "Beta")]
    assert [row["tripId"] for row in fire(absent, times)] == ["W2"]
    assert fire(empty, times) == []


def test_the_fold_is_javas_and_not_casefold():
    """`Straße` against `STRASSE`: equal under `str.casefold`, unequal under `equalsIgnoreCase`.

    Java compares code unit by code unit after single-unit case mapping, so a fold that changes
    length cannot match. Without this case every other test of the fold is ASCII, and swapping
    `equals_ignore_case` for `casefold()` equality would pass all of them: `javatext`'s own tests
    prove the helper is right, not that this rule calls it.

    The second half is the control: the same pair differing only by case, with no length change,
    still matches. Otherwise this test would also pass against a rule that had stopped folding.
    """
    sharp = [stop("A", "Straße"), *STOPS]
    assert fire([trip(2, "T1", "STRASSE")], stop_times("T1", "A", "B", "C"), sharp) == []
    lower = [stop("A", "straße"), *STOPS]
    assert len(fire([trip(2, "T1", "STRAßE")], stop_times("T1", "A", "B", "C"), lower)) == 1
