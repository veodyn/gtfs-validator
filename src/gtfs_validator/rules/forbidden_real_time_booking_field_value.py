"""BookingRulesEntityValidator: real-time rules may not carry any prior-notice field.

A rule bookable in real time has nothing to say about notice periods, so all seven
prior-notice fields are forbidden at once.

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

CODE = "forbidden_real_time_booking_field_value"


@rule(code=CODE, severity=Severity.ERROR, filename="booking_rules.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if row.get("booking_type") != booking.REALTIME:
        return
    field_names = booking.forbidden_field_names(row, booking.REAL_TIME_FORBIDDEN)
    if not field_names:
        return
    yield Notice(CODE, Severity.ERROR, {**booking.identity(row), "fieldNames": field_names})
