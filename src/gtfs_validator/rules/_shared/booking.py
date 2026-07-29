"""What BookingRulesEntityValidator's eleven codes share.

Upstream is one SingleEntityValidator emitting eleven notices; here each code is its own
module, so the field names, the booking types and the "which fields are forbidden for
this type" lists live here once. A twelfth notice class sits in the same file and is one
of the four upstream constructs nowhere, so there is nothing to implement for it.

Two details are easy to get wrong and are both measured:

- **Presence is a set-value test, not a truth test and not a column test.**
  `hasPriorNoticeDurationMin()` is true for an explicit `0` and false for an empty cell
  in a column that exists, so a rule must ask whether the value is absent rather than
  whether it is falsy or whether the header carried the field. Both halves measured: a
  REALTIME rule declaring `prior_notice_duration_min,0` is reported, and a SAMEDAY rule
  leaving the same column blank draws missing_prior_notice_duration_min.
- **`fieldNames` is ordered.** It is `String.join(", ", fields)` over the finder's
  *argument* order, not sorted and not the header's order, so the lists below are
  transcribed in upstream's order and must stay that way.
"""

from __future__ import annotations

DURATION_MIN = "prior_notice_duration_min"
DURATION_MAX = "prior_notice_duration_max"
LAST_DAY = "prior_notice_last_day"
LAST_TIME = "prior_notice_last_time"
START_DAY = "prior_notice_start_day"
START_TIME = "prior_notice_start_time"
SERVICE_ID = "prior_notice_service_id"

# GtfsBookingType.
REALTIME = 0
SAMEDAY = 1
PRIORDAY = 2

# Argument order of findForbiddenRealTimeFields, findForbiddenSameDayFields and
# findForbiddenPriorDayFields respectively. The order is part of the output.
REAL_TIME_FORBIDDEN = (
    DURATION_MIN,
    DURATION_MAX,
    LAST_DAY,
    LAST_TIME,
    START_DAY,
    START_TIME,
    SERVICE_ID,
)
SAME_DAY_FORBIDDEN = (LAST_DAY, LAST_TIME, SERVICE_ID)
PRIOR_DAY_FORBIDDEN = (DURATION_MIN, DURATION_MAX)


def has(row: dict, field: str) -> bool:
    """`hasX()`: the field parsed to a value, even if that value is zero.

    An empty cell is absent however the header reads, which is why this tests the parsed
    value rather than the column.
    """
    return row.get(field) is not None


def forbidden_field_names(row: dict, fields: tuple[str, ...]) -> str:
    """The `fieldNames` context value: present fields, in the given order, ", "-joined."""
    return ", ".join(field for field in fields if has(row, field))


def identity(row: dict) -> dict:
    """The two context fields ten of the eleven notices open with.

    `prior_notice_last_day_after_start_day` is the exception and carries no
    bookingRuleId, measured, so it builds its context without this.
    """
    return {
        "csvRowNumber": row["_row_number"],
        "bookingRuleId": row.get("booking_rule_id") or "",
    }
