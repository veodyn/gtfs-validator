"""PickupDropOffWindowValidator, its three codes.

Every expectation is the jar's output on three probe feeds:

- `pdow`, twelve stop_times rows covering each branch once, including two clean controls
  and one row that draws two codes at once;
- `pdow2`, a window past midnight and a window whose start does not parse;
- `pdow7`, whose first two rows are ordinary stop times with both times and no window,
  which is the control for the early return every real feed depends on.

The measurement that contradicted a plain reading is `pdow2`'s third row: an unparsable
`start_pickup_drop_off_window` beside a valid end window draws `invalid_time` and **no**
window notice, where reading the Java alone predicts a `missing_pickup_or_drop_off_window`
carrying the end. A row whose field fails to parse never becomes an entity, so the
single-entity validator is not called for it at all.

Nothing here reproduces that, and no unit test in this build can: the row never reaches a
rule, because the typing stage does not store a row that drew an ERROR. It is a property of
the store, tested in tests/test_typing_stage.py, and these three rules inherit it.
"""

from __future__ import annotations

import datetime

import pytest

from gtfs_validator.context import Context
from gtfs_validator.notices import Severity
from gtfs_validator.rules import registry
from stoptimerows import (
    STOP_TIMES,
    T0700,
    T0800,
    T0830,
    T0900,
    T1000,
    T1200,
    T2500,
    T2530,
    T2600,
    stop_time,
)

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")

FORBIDDEN = "forbidden_arrival_or_departure_time"
MISSING_WINDOW = "missing_pickup_or_drop_off_window"
INVALID_WINDOW = "invalid_pickup_drop_off_window"


def fire(code, row):
    registry.load_rules()
    return [notice.context for notice in registry.REGISTRY[code].func(row, CTX)]


# --- forbidden_arrival_or_departure_time -------------------------------------------------


def test_an_arrival_beside_a_window_omits_the_departure_key():
    """Probe row 4. The notice is constructed with an explicit null for the absent time and
    gson drops a null, so the key is *omitted* rather than rendered as "00:00:00".

    That is the opposite of forbidden_pickup_type next door, whose absent window renders as
    the GtfsTime default. Both read the same field type; what differs is that this
    constructor is passed null and that one is passed the getter.
    """
    got = fire(
        FORBIDDEN,
        stop_time(4, "T2", arrival_time=T0800, start=T1000, end=T1200),
    )
    assert got == [
        {
            "csvRowNumber": 4,
            "arrivalTime": "08:00:00",
            "startPickupDropOffWindow": "10:00:00",
            "endPickupDropOffWindow": "12:00:00",
        }
    ]


def test_a_departure_beside_a_window_omits_the_arrival_key():
    """Probe row 5."""
    got = fire(
        FORBIDDEN,
        stop_time(5, "T2", departure_time=T0900, start=T1000, end=T1200),
    )
    assert got == [
        {
            "csvRowNumber": 5,
            "departureTime": "09:00:00",
            "startPickupDropOffWindow": "10:00:00",
            "endPickupDropOffWindow": "12:00:00",
        }
    ]


def test_both_times_beside_a_window_carry_all_four_keys():
    """Probe row 6."""
    got = fire(
        FORBIDDEN,
        stop_time(
            6,
            "T3",
            arrival_time=T0800,
            departure_time=T0830,
            start=T1000,
            end=T1200,
        ),
    )
    assert got == [
        {
            "csvRowNumber": 6,
            "arrivalTime": "08:00:00",
            "departureTime": "08:30:00",
            "startPickupDropOffWindow": "10:00:00",
            "endPickupDropOffWindow": "12:00:00",
        }
    ]


def test_a_time_beside_half_a_window_omits_the_other_half():
    """Probe row 12, the row that draws two codes. The forbidden notice omits both the
    departure and the end window, so two of its four time keys are absent at once."""
    row = stop_time(12, "T6", arrival_time=T0700, start=T1000)
    assert fire(FORBIDDEN, row) == [
        {
            "csvRowNumber": 12,
            "arrivalTime": "07:00:00",
            "startPickupDropOffWindow": "10:00:00",
        }
    ]
    assert fire(MISSING_WINDOW, row) == [
        {"csvRowNumber": 12, "startPickupDropOffWindow": "10:00:00"}
    ]


def test_a_time_without_any_window_is_not_reported():
    """pdow7 rows 2 and 3, which are ordinary stop times with both times and no window.

    The validator returns before the arrival test unless a window is present, which is what
    keeps every stop time in every non-flex feed out of this code. Added after a review
    pointed out that the assertion had no probe behind it: it was the one case here restating
    the implementation rather than a measurement.
    """
    assert fire(FORBIDDEN, stop_time(2, "TP", arrival_time=T0800, departure_time=T0800)) == []


def test_a_window_without_a_time_is_not_reported():
    """Probe rows 2 and 3, the clean controls."""
    assert fire(FORBIDDEN, stop_time(2, start=T1000, end=T1200)) == []


# --- missing_pickup_or_drop_off_window ----------------------------------------------------


def test_a_start_without_an_end_carries_only_the_start():
    """Probe row 7."""
    assert fire(MISSING_WINDOW, stop_time(7, "T3", start=T1000)) == [
        {"csvRowNumber": 7, "startPickupDropOffWindow": "10:00:00"}
    ]


def test_an_end_without_a_start_carries_only_the_end():
    """Probe row 8."""
    assert fire(MISSING_WINDOW, stop_time(8, "T4", end=T1200)) == [
        {"csvRowNumber": 8, "endPickupDropOffWindow": "12:00:00"}
    ]


def test_a_complete_window_is_not_reported():
    assert fire(MISSING_WINDOW, stop_time(2, start=T1000, end=T1200)) == []


def test_a_half_window_past_midnight_renders_past_midnight():
    """pdow2 row 3. GtfsTime counts seconds from noon minus twelve hours and its renderer
    does not wrap, so a 26:00:00 window reads back as 26:00:00 rather than 02:00:00."""
    assert fire(MISSING_WINDOW, stop_time(3, "U1", start=T2600)) == [
        {"csvRowNumber": 3, "startPickupDropOffWindow": "26:00:00"}
    ]


# --- invalid_pickup_drop_off_window -------------------------------------------------------


def test_a_start_after_its_end_is_invalid():
    """Probe row 9."""
    got = fire(INVALID_WINDOW, stop_time(9, "T4", start=T1200, end=T1000))
    assert got == [
        {
            "csvRowNumber": 9,
            "startPickupDropOffWindow": "12:00:00",
            "endPickupDropOffWindow": "10:00:00",
        }
    ]


def test_a_start_equal_to_its_end_is_invalid():
    """Probe row 10. The end must be *strictly* later, so a zero-length window is reported."""
    got = fire(INVALID_WINDOW, stop_time(10, "T5", start=T1200, end=T1200))
    assert got == [
        {
            "csvRowNumber": 10,
            "startPickupDropOffWindow": "12:00:00",
            "endPickupDropOffWindow": "12:00:00",
        }
    ]


def test_a_window_crossing_midnight_is_valid():
    """Probe row 11: 08:00:00 to 25:30:00 draws nothing, so the comparison is on the stored
    seconds and not on a wrapped clock time."""
    assert fire(INVALID_WINDOW, stop_time(11, "T5", start=T0800, end=T2530)) == []


def test_an_inverted_window_past_midnight_is_reported_unwrapped():
    """pdow2 row 2, the only measured notice carrying two times past midnight."""
    got = fire(INVALID_WINDOW, stop_time(2, "U1", start=T2530, end=T2500))
    assert got == [
        {
            "csvRowNumber": 2,
            "startPickupDropOffWindow": "25:30:00",
            "endPickupDropOffWindow": "25:00:00",
        }
    ]


def test_half_a_window_is_never_invalid():
    """The missing-window branch returns, so a row with one end draws that code and not this
    one. Were the return dropped, this row would compare a real time against an absent one."""
    assert fire(INVALID_WINDOW, stop_time(7, "T3", start=T1000)) == []
    assert fire(INVALID_WINDOW, stop_time(8, "T4", end=T1200)) == []


# --- the shared header gate ---------------------------------------------------------------


@pytest.mark.parametrize("code", [FORBIDDEN, MISSING_WINDOW, INVALID_WINDOW])
def test_all_three_are_gated_on_the_window_columns(code):
    """`shouldCallValidate` asks for either window column, so a stop_times.txt declaring
    neither never runs the validator.

    Not observable through the notices, since a row of a table without those columns has no
    window either way, and asserted on the spec for that reason: it is upstream's own gate,
    and the registration is where this build records it.
    """
    # load_rules() first, as `fire` does: the registry is populated by importing the rule
    # modules, so this assertion run on its own raises KeyError otherwise.
    registry.load_rules()
    spec = registry.REGISTRY[code]
    assert spec.filename == STOP_TIMES
    assert spec.requires_any_column == (
        "start_pickup_drop_off_window",
        "end_pickup_drop_off_window",
    )
    assert spec.severity is Severity.ERROR
