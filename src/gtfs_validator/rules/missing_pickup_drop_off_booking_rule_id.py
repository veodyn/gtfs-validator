"""PickupBookingRuleIdValidator: a phone-booked window needs the rule that describes it.

Two independent branches, one per direction, and a stop time can trip both: a row whose pickup
and drop-off are each MUST_PHONE with both windows and no rule ids draws **two** notices with
identical context. Measured, so the duplicate is the contract rather than something to collapse.

Each notice reports both types, but only the one its branch is about is guaranteed present: the
other is passed as null when the row omits it, and Gson drops a null, so `dropOffType` is
missing entirely from a row that sets no drop_off_type. The types report as enum *names*, not
numbers.

Gated on booking_rules.txt existing *and loading*, and on stop_times.txt declaring at least one
of the two type columns, which is a header test.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.enums import enum_name
from gtfs_validator.rules.registry import file_rule, scan_rule

CODE = "missing_pickup_drop_off_booking_rule_id"
STOP_TIMES = "stop_times.txt"
BOOKING_RULES = "booking_rules.txt"
PICKUP_TYPE = "pickup_type"
DROP_OFF_TYPE = "drop_off_type"

# GtfsPickupDropOff.MUST_PHONE.
MUST_PHONE = 2

# (type field, window field, booking rule field) for the pickup branch then the drop-off branch.
BRANCHES = (
    (PICKUP_TYPE, "start_pickup_drop_off_window", "pickup_booking_rule_id"),
    (DROP_OFF_TYPE, "end_pickup_drop_off_window", "drop_off_booking_rule_id"),
)


class _Consumer:
    def row(self, row: dict) -> list[Notice] | None:
        notices = None
        for type_field, window_field, rule_field in BRANCHES:
            if row.get(type_field) != MUST_PHONE:
                continue
            if row.get(window_field) is None or row.get(rule_field) is not None:
                continue
            notices = notices or []
            notices.append(Notice(CODE, Severity.WARNING, _context(row)))
        return notices

    def finish(self) -> Iterator[Notice]:
        return iter(())


@scan_rule(code=CODE, table=STOP_TIMES)
def scan(feed, ctx: Context) -> _Consumer | None:
    """The hub factory: None when the gates below say the validator never runs.

    is_missing is not enough: upstream's gate is `!bookingRulesTable.isMissingFile()` *and*
    the container being injected at all, so a booking_rules.txt that is present and failed to
    load also skips the validator. Measured on one missing its required booking_type column,
    where the jar reports neither notice and reading it as merely absent reported both.
    """
    if feed.is_missing(BOOKING_RULES) or feed.dependency_failed(BOOKING_RULES):
        return None
    if not any(feed.has_column(STOP_TIMES, column) for column in (PICKUP_TYPE, DROP_OFF_TYPE)):
        return None
    return _Consumer()


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    """The sequential path, on the same consumer the hub feeds."""
    consumer = scan(feed, ctx)
    if consumer is None:
        return
    for row in feed.rows(STOP_TIMES):
        yield from consumer.row(row) or ()
    yield from consumer.finish()


def _context(row: dict) -> dict:
    """Both types by name, omitting whichever the row does not carry."""
    context: dict = {"csvRowNumber": row["_row_number"]}
    for field, key in ((PICKUP_TYPE, "pickupType"), (DROP_OFF_TYPE, "dropOffType")):
        value = row.get(field)
        if value is None:
            continue
        context[key] = enum_name(STOP_TIMES, field, value) or ""
    return context
