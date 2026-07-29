"""BookingRulesEntityValidator: a start day without a start time is incomplete.

See forbidden_prior_notice_start_time for the other half. This one reports the day it
has rather than the time it lacks.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import booking
from gtfs_validator.rules.registry import rule

CODE = "missing_prior_notice_start_time"


@rule(code=CODE, severity=Severity.ERROR, filename="booking_rules.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if booking.has(row, booking.START_TIME) or not booking.has(row, booking.START_DAY):
        return
    yield Notice(
        CODE,
        Severity.ERROR,
        {**booking.identity(row), "priorNoticeStartDay": row[booking.START_DAY]},
    )
