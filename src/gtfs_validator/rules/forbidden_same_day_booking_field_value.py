"""BookingRulesEntityValidator: same-day rules may not carry a last-day or service deadline.

Same-day booking still has a duration, so the two duration fields stay legal here and
only the day-scale deadlines are forbidden.

`fieldNames` lists every forbidden field the row actually declares, in upstream's
argument order and joined with ", ". A row carrying none of them draws nothing, which is
why the finder's emptiness check matters rather than the booking type alone.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import booking
from gtfs_validator.rules.registry import rule

CODE = "forbidden_same_day_booking_field_value"


@rule(code=CODE, severity=Severity.ERROR, filename="booking_rules.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if row.get("booking_type") != booking.SAMEDAY:
        return
    field_names = booking.forbidden_field_names(row, booking.SAME_DAY_FORBIDDEN)
    if not field_names:
        return
    yield Notice(CODE, Severity.ERROR, {**booking.identity(row), "fieldNames": field_names})
