"""StopTimesRecordValidator: a flex trip whose one stop time needs a second.

Every expectation is the jar's output on six probe feeds:

- `stmrec`, eight stop_times rows covering the four conditions and each location spelling;
- `pdow5`, a lone stop time whose trip is not declared in trips.txt;
- `pdow3` against `pdow4`, the same two cases with and without an unparsable row beside
  them, which is what separates this validator's gate from the window validator's;
- `pdow6`, three lone flex trips written in descending id order, which measures emission
  order as file order rather than sorted;
- `pdow7` and `pdow8`, the blank and explicitly-zero type columns and a file declaring no
  type column at all.

`pdow3` against `pdow4` is the measurement worth keeping: with one unparsable row in
stop_times.txt the jar reports `invalid_integer`, drops `missing_stop_times_record` entirely,
and still reports `missing_pickup_or_drop_off_window` on the clean row beside it. Two
validators over one table, two different answers to the same broken row.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.notices import Severity
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import DependencyFailed
from stoptimerows import MUST_PHONE, REGULAR, STOP_TIMES, T1000, T1200, stop_time

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")

CODE = "missing_stop_times_record"

# `shouldCallValidate`'s four columns, spelled out rather than imported from the rule so the
# gate's shape is asserted independently of the code implementing it.
REQUIRED_COLUMNS = (
    "start_pickup_drop_off_window",
    "end_pickup_drop_off_window",
    "pickup_type",
    "drop_off_type",
)


def fire(tables, unindexable=frozenset()):
    registry.load_rules()
    feed = FakeFeed(tables, unindexable=unindexable)
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(feed, CTX)]


def record_row(number, trip_id, **fields):
    """A row meeting every one of the four conditions, so a test can break exactly one."""
    return stop_time(
        number,
        trip_id,
        start=T1000,
        end=T1200,
        pickup_type=MUST_PHONE,
        drop_off_type=MUST_PHONE,
        **fields,
    )


def test_a_lone_flex_stop_time_names_its_location_group():
    """stmrec row 2. `locationId` is present and empty: the notice takes the getter rather
    than a null, and the generated entity's default for an unset String is "", which gson
    writes. Omitting the key instead is the window validator's convention, and these two sit
    one file apart with opposite answers.
    """
    tables = {STOP_TIMES: [record_row(2, "TA", location_group_id="LG1")]}
    assert fire(tables) == [
        {"csvRowNumber": 2, "tripId": "TA", "locationGroupId": "LG1", "locationId": ""}
    ]


def test_a_lone_flex_stop_time_names_its_geojson_location():
    """stmrec row 3."""
    tables = {STOP_TIMES: [record_row(3, "TB", location_id="area1")]}
    assert fire(tables) == [
        {"csvRowNumber": 3, "tripId": "TB", "locationGroupId": "", "locationId": "area1"}
    ]


def test_a_lone_flex_stop_time_at_a_plain_stop_carries_two_empty_keys():
    """stmrec row 4: a stop_id and no flex location at all still draws the notice, with both
    location keys present and empty. Nothing in the validator asks where the stop time is."""
    tables = {STOP_TIMES: [record_row(4, "TC", stop_id="S1")]}
    assert fire(tables) == [
        {"csvRowNumber": 4, "tripId": "TC", "locationGroupId": "", "locationId": ""}
    ]


def test_a_trip_with_two_stop_times_is_not_reported():
    """stmrec rows 5 and 6. The count is over stop times sharing a trip, so the second row
    clears both."""
    tables = {
        STOP_TIMES: [
            record_row(5, "TD", location_group_id="LG1"),
            record_row(6, "TD", location_group_id="LG1"),
        ]
    }
    assert fire(tables) == []


def test_the_two_stop_times_of_a_trip_need_not_be_adjacent():
    """A lone flex trip written between a trip's two rows.

    `byTripId` groups the whole table, so the count is global and not a run of neighbours.
    Added after a review pointed out that the adjacent-rows fixture above would also pass an
    implementation counting consecutive rows, which is a plausible way to write this rule
    while streaming: the count a row needs is over rows that come after it.
    """
    tables = {
        STOP_TIMES: [
            record_row(2, "TD", location_group_id="LG1"),
            record_row(3, "TLONE", location_group_id="LG1"),
            record_row(4, "TD", location_group_id="LG1"),
        ]
    }
    assert fire(tables) == [
        {"csvRowNumber": 3, "tripId": "TLONE", "locationGroupId": "LG1", "locationId": ""}
    ]


def test_notices_come_out_in_file_order():
    """pdow6: three lone flex trips written in descending id order and reported in that same
    order, so the container yields entities as loaded rather than sorted by trip.

    Three notices are enough to pin an order, because `sampleNotices` preserves emission
    order; the 1,000-sample cap is where order starts deciding *which* notices survive, and
    this is the cheap way to measure the order that cap will apply. The differential harness
    cannot catch a regression here, since it compares samples as a sorted multiset.
    """
    tables = {
        STOP_TIMES: [
            record_row(2, "TZ"),
            record_row(3, "TM"),
            record_row(4, "TA"),
        ]
    }
    assert [notice["tripId"] for notice in fire(tables)] == ["TZ", "TM", "TA"]


@pytest.mark.parametrize(
    ("pickup", "drop_off", "probe"),
    [
        (MUST_PHONE, REGULAR, "stmrec row 7"),
        (REGULAR, MUST_PHONE, "stmrec row 8"),
        (REGULAR, REGULAR, "pdow7's TZERO"),
        (None, None, "pdow7's TBLANK"),
    ],
)
def test_both_types_must_be_must_phone(pickup, drop_off, probe):
    """Four measured rows, one per combination that is not must-phone at both ends.

    The last two were added after a review caught them being asserted rather than measured.
    They are the interesting pair: an unset type reads as `REGULAR` rather than as an absence,
    so a lone flex trip leaving both cells blank is a row that meets every *other* condition
    and is still not reported. Inferring that from the explicit zero would have been a guess
    about the generated getter's default, which is the class of guess this project keeps
    getting wrong.
    """
    # Both keys are set even when the value is None, because pdow7's TBLANK *declares* both
    # columns and leaves the cells empty. Omitting the keys would fail the header gate below
    # instead of the type predicate, and the test would pass for the wrong reason.
    row = stop_time(7, "TE", start=T1000, end=T1200, pickup_type=pickup, drop_off_type=drop_off)
    assert fire({STOP_TIMES: [row]}) == [], probe


@pytest.mark.parametrize("undeclared", REQUIRED_COLUMNS)
def test_a_file_missing_any_one_required_column_is_not_scanned(undeclared):
    """pdow8: a lone flex trip with a complete window in a stop_times.txt declaring neither
    type column. The jar reports nothing, and `shouldCallValidate` is why: it wants all four
    columns, so the validator never runs.

    That gate cannot change the output, since an undeclared pickup_type reads as REGULAR and
    fails the predicate anyway. What it changes is whether the largest file in a feed is
    scanned at all, and the raise is the only way that is observable from here: with the table
    also marked failed, a gated rule returns while an ungated one reaches `rows()` and raises.

    Parametrised over the four columns one at a time, because a case dropping both type
    columns at once passes against a gate that tests only one of them. Upstream's condition is
    a conjunction, so each conjunct needs its own case.
    """
    row = record_row(2, "TNOTYPE")
    del row[undeclared]
    assert fire({STOP_TIMES: [row]}) == []
    assert fire({STOP_TIMES: [row]}, unindexable=frozenset({STOP_TIMES})) == []


def test_half_a_window_is_not_reported():
    """stmrec row 9, which draws missing_pickup_or_drop_off_window and not this code."""
    row = stop_time(9, "TG", start=T1000, pickup_type=MUST_PHONE, drop_off_type=MUST_PHONE)
    assert fire({STOP_TIMES: [row]}) == []


def test_a_stop_time_whose_trip_is_undeclared_is_still_counted():
    """pdow5. The count comes from `byTripId` over stop_times.txt, not from trips.txt, so a
    dangling trip reference draws the notice naming the id it could not resolve."""
    tables = {STOP_TIMES: [record_row(2, "NOSUCH")]}
    assert fire(tables) == [
        {"csvRowNumber": 2, "tripId": "NOSUCH", "locationGroupId": "", "locationId": ""}
    ]


def test_a_failed_stop_times_table_silences_the_rule():
    """pdow3 against pdow4, which is the whole point of that pair.

    Asserted as the raise rather than as an empty result: reading through `rows()` is what
    silences a FileValidator, and the runner discards whatever the rule had yielded. Reading
    `entity_rows()` instead would report the clean row that upstream never sees.
    """
    tables = {STOP_TIMES: [record_row(3, "G2")]}
    with pytest.raises(DependencyFailed):
        fire(tables, unindexable=frozenset({STOP_TIMES}))


def test_the_code_is_an_error():
    # load_rules() first, as `fire` does: the registry is populated by importing the rule
    # modules, so a registry assertion run on its own raises KeyError otherwise. A review
    # found this by running each of these tests in isolation.
    registry.load_rules()
    assert registry.FILE_REGISTRY[CODE].severity is Severity.ERROR
