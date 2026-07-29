"""BookingRulesEntityValidator: the minimum notice cannot exceed the maximum.

Checked only when both are present, and the comparison is strict, so an equal pair is
valid. Independent of the booking type: upstream runs this outside the type switch, so a
prior-day rule draws both this and the forbidden-duration notice for the same two
fields.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import booking
from gtfs_validator.rules.registry import rule

CODE = "invalid_prior_notice_duration_min"


@rule(code=CODE, severity=Severity.ERROR, filename="booking_rules.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if not (booking.has(row, booking.DURATION_MIN) and booking.has(row, booking.DURATION_MAX)):
        return
    minimum, maximum = row[booking.DURATION_MIN], row[booking.DURATION_MAX]
    if maximum >= minimum:
        return
    yield Notice(
        CODE,
        Severity.ERROR,
        {
            **booking.identity(row),
            "priorNoticeDurationMin": minimum,
            "priorNoticeDurationMax": maximum,
        },
    )
