"""BookingRulesEntityValidator: a start time without a start day means nothing.

The other half of a mutual pair with missing_prior_notice_start_time: one fires when the
time is present without the day, the other when the day is present without the time, so
exactly one can fire per row.

The time renders as HH:MM:SS through GtfsTime.toHHMMSS, which is why the store's seconds
go through the shared renderer rather than str().
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import booking
from gtfs_validator.rules._shared.render import hhmmss
from gtfs_validator.rules.registry import rule

CODE = "forbidden_prior_notice_start_time"


@rule(code=CODE, severity=Severity.ERROR, filename="booking_rules.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if not booking.has(row, booking.START_TIME) or booking.has(row, booking.START_DAY):
        return
    yield Notice(
        CODE,
        Severity.ERROR,
        {**booking.identity(row), "priorNoticeStartTime": hhmmss(row[booking.START_TIME])},
    )
