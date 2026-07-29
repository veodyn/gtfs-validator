"""BookingRulesEntityValidator: a prior-day rule needs a last time to book.

The time half of the pair described in missing_prior_notice_last_day.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import booking
from gtfs_validator.rules.registry import rule

CODE = "missing_prior_notice_last_time"


@rule(code=CODE, severity=Severity.ERROR, filename="booking_rules.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if row.get("booking_type") != booking.PRIORDAY or booking.has(row, booking.LAST_TIME):
        return
    yield Notice(CODE, Severity.ERROR, booking.identity(row))
