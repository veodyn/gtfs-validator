"""BookingRulesEntityValidator, all eleven reachable codes.

Every expectation is the jar's output on `brfeed`, a booking_rules.txt whose seven rows
cover each branch once, including a clean control row, and on `brzero`, which sets every
day, time and duration field to an explicit zero. The twelfth notice in that validator,
`missing_prior_day_booking_field_value`, is declared in upstream's deprecated package and
constructed nowhere, so there is nothing to assert about it.
"""

from __future__ import annotations

import datetime

import pytest

from gtfs_validator.context import Context
from gtfs_validator.notices import Severity
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")

REALTIME, SAMEDAY, PRIORDAY = 0, 1, 2


def row(number, rule_id, booking_type, **fields):
    """One typed booking_rules row, with the times already in seconds as the store holds
    them.

    Absent fields are omitted here, where a production row carries every schema key set
    to None. `row.get()` reads both the same way, so this is a shorter fixture rather
    than a different input; what matters is that an absent field and an explicit 0 stay
    distinguishable, since `hasPriorNoticeDurationMin()` is true for the zero.
    """
    return {
        "_row_number": number,
        "booking_rule_id": rule_id,
        "booking_type": booking_type,
        **fields,
    }


# The seven probe rows, in file order.
BR1 = row(
    2,
    "BR1",
    REALTIME,
    prior_notice_duration_min=5,
    prior_notice_duration_max=10,
    prior_notice_last_day=1,
    prior_notice_last_time=36000,
    prior_notice_start_day=2,
    prior_notice_start_time=32400,
    prior_notice_service_id="SV",
)
BR2 = row(
    3,
    "BR2",
    SAMEDAY,
    prior_notice_last_day=1,
    prior_notice_last_time=36000,
    prior_notice_service_id="SV",
)
BR3 = row(4, "BR3", PRIORDAY, prior_notice_duration_min=5, prior_notice_duration_max=10)
BR4 = row(
    5,
    "BR4",
    PRIORDAY,
    prior_notice_duration_min=20,
    prior_notice_duration_max=10,
    prior_notice_last_day=1,
    prior_notice_last_time=36000,
)
BR5 = row(
    6,
    "BR5",
    PRIORDAY,
    prior_notice_last_day=1,
    prior_notice_last_time=36000,
    prior_notice_start_time=32400,
)
BR6 = row(
    7,
    "BR6",
    PRIORDAY,
    prior_notice_last_day=5,
    prior_notice_last_time=36000,
    prior_notice_start_day=3,
)
BR7 = row(8, "BR7", PRIORDAY, prior_notice_last_day=1, prior_notice_last_time=36000)
ALL_ROWS = [BR1, BR2, BR3, BR4, BR5, BR6, BR7]

MEASURED = {
    "forbidden_real_time_booking_field_value": [
        {
            "csvRowNumber": 2,
            "bookingRuleId": "BR1",
            "fieldNames": "prior_notice_duration_min, prior_notice_duration_max, prior_notice_last_day, "
            "prior_notice_last_time, prior_notice_start_day, prior_notice_start_time, "
            "prior_notice_service_id",
        },
    ],
    "forbidden_same_day_booking_field_value": [
        {
            "csvRowNumber": 3,
            "bookingRuleId": "BR2",
            "fieldNames": "prior_notice_last_day, prior_notice_last_time, prior_notice_service_id",
        },
    ],
    "forbidden_prior_day_booking_field_value": [
        {
            "csvRowNumber": 4,
            "bookingRuleId": "BR3",
            "fieldNames": "prior_notice_duration_min, prior_notice_duration_max",
        },
        {
            "csvRowNumber": 5,
            "bookingRuleId": "BR4",
            "fieldNames": "prior_notice_duration_min, prior_notice_duration_max",
        },
    ],
    "missing_prior_notice_duration_min": [{"csvRowNumber": 3, "bookingRuleId": "BR2"}],
    "invalid_prior_notice_duration_min": [
        {
            "csvRowNumber": 5,
            "bookingRuleId": "BR4",
            "priorNoticeDurationMin": 20,
            "priorNoticeDurationMax": 10,
        },
    ],
    "missing_prior_notice_last_day": [{"csvRowNumber": 4, "bookingRuleId": "BR3"}],
    "missing_prior_notice_last_time": [{"csvRowNumber": 4, "bookingRuleId": "BR3"}],
    "forbidden_prior_notice_start_day": [
        {
            "csvRowNumber": 2,
            "bookingRuleId": "BR1",
            "priorNoticeStartDay": 2,
            "priorNoticeDurationMax": 10,
        },
    ],
    "forbidden_prior_notice_start_time": [
        {"csvRowNumber": 6, "bookingRuleId": "BR5", "priorNoticeStartTime": "09:00:00"},
    ],
    "missing_prior_notice_start_time": [
        {"csvRowNumber": 7, "bookingRuleId": "BR6", "priorNoticeStartDay": 3},
    ],
    "prior_notice_last_day_after_start_day": [
        {"csvRowNumber": 7, "priorNoticeLastDay": 5, "priorNoticeStartDay": 3},
    ],
}


def fire(code, rows):
    registry.load_rules()
    spec = registry.REGISTRY[code]
    return [n.context for entity in rows for n in spec.func(entity, CTX)]


@pytest.mark.parametrize(("code", "expected"), sorted(MEASURED.items()))
def test_booking_rule_matches_the_jar(code, expected):
    assert fire(code, ALL_ROWS) == expected


@pytest.mark.parametrize("code", sorted(MEASURED))
def test_the_clean_control_row_draws_nothing(code):
    # BR7 is a well-formed PRIORDAY rule. The parametrised assertion above would also
    # catch an extra notice on it; this pins the clean row per code, so a failure names
    # the rule that went wrong rather than a diff of two eleven-entry tables.
    assert fire(code, [BR7]) == []


@pytest.mark.parametrize("code", sorted(MEASURED))
def test_every_booking_code_is_an_error(code):
    registry.load_rules()
    assert registry.REGISTRY[code].severity is Severity.ERROR
