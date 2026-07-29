"""BookingRulesEntityValidator: a same-day rule needs a minimum notice duration.

Same shape as missing_prior_notice_last_day and missing_prior_notice_last_time: a booking
type plus one absent field. A prior-day rule leaving this out is fine, and a real-time
rule setting it is a different notice.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import booking
from gtfs_validator.rules.registry import rule

CODE = "missing_prior_notice_duration_min"


@rule(code=CODE, severity=Severity.ERROR, filename="booking_rules.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if row.get("booking_type") != booking.SAMEDAY or booking.has(row, booking.DURATION_MIN):
        return
    yield Notice(CODE, Severity.ERROR, booking.identity(row))
