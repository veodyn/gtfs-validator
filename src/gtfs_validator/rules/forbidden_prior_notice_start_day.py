"""BookingRulesEntityValidator: a start day and a maximum duration are alternatives.

Both express the far end of the booking window, one in days and one in minutes, so
declaring both is contradictory rather than merely redundant. Not gated on booking type.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import booking
from gtfs_validator.rules.registry import rule

CODE = "forbidden_prior_notice_start_day"


@rule(code=CODE, severity=Severity.ERROR, filename="booking_rules.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if not (booking.has(row, booking.DURATION_MAX) and booking.has(row, booking.START_DAY)):
        return
    yield Notice(
        CODE,
        Severity.ERROR,
        {
            **booking.identity(row),
            "priorNoticeStartDay": row[booking.START_DAY],
            "priorNoticeDurationMax": row[booking.DURATION_MAX],
        },
    )
