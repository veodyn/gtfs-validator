"""BookingRulesEntityValidator: the booking window must not close before it opens.

The days count backwards from the trip, so a *larger* last day is earlier: last day 5
against start day 3 means booking closes two days before it opens. The comparison is
strict, so an equal pair is a single valid day.

The only one of the eleven that carries no bookingRuleId, measured, so it builds its context
directly rather than through the shared identity helper.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import booking
from gtfs_validator.rules.registry import rule

CODE = "prior_notice_last_day_after_start_day"


@rule(code=CODE, severity=Severity.ERROR, filename="booking_rules.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if not (booking.has(row, booking.LAST_DAY) and booking.has(row, booking.START_DAY)):
        return
    last_day, start_day = row[booking.LAST_DAY], row[booking.START_DAY]
    if last_day <= start_day:
        return
    yield Notice(
        CODE,
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            "priorNoticeLastDay": last_day,
            "priorNoticeStartDay": start_day,
        },
    )
