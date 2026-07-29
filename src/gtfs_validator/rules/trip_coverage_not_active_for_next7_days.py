"""DateTripsValidator: the majority service window misses the coming week.

The one notice in this cohort whose dates are GtfsDate rather than
LocalDate.toString, so eight digits and no dashes. The manifest types its three
fields as object where the other five rules' are string, which is the signal.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.calendars import render_gtfs_date
from gtfs_validator.rules._shared.trip_calendar import (
    count_trips_by_date,
    majority_service_coverage,
)
from gtfs_validator.rules.registry import file_rule

COVERAGE_DAYS = 7


@file_rule(code="trip_coverage_not_active_for_next7_days", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    coverage = majority_service_coverage(count_trips_by_date(feed))
    if coverage is None:
        return
    start, end = coverage
    # A day difference rather than a shifted horizon: a validation date in the last
    # week of year 9999 is accepted, and shifting past date.max raises
    # OverflowError where Java computes a year-10000 horizon and still decides.
    # Either bound failing is enough: a window starting after today, or ending
    # before the horizon, leaves part of the week uncovered.
    if not (start > ctx.date or (end - ctx.date).days < COVERAGE_DAYS):
        return
    yield Notice(
        "trip_coverage_not_active_for_next7_days",
        Severity.WARNING,
        {
            "currentDate": render_gtfs_date(ctx.date),
            "serviceWindowStartDate": render_gtfs_date(start),
            "serviceWindowEndDate": render_gtfs_date(end),
        },
    )
