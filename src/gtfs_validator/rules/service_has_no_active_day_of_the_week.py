"""ServiceHasNoActiveDayOfTheWeekValidator: a calendar row with every day off.

A file rule rather than an entity rule because upstream makes it a FileValidator.
That is not cosmetic: an entity rule would be skipped when calendar.txt failed
its header check, and a file rule reads whatever the store holds either way.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.calendars import NOT_AVAILABLE, WEEKDAY_FIELDS
from gtfs_validator.rules.registry import file_rule


@file_rule(code="service_has_no_active_day_of_the_week", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for row in feed.rows("calendar.txt"):
        # Upstream also requires hasServiceId, so a row whose service_id failed
        # to parse is skipped rather than reported without one.
        if row.get("service_id") is None:
            continue
        # Every day must be exactly NOT_AVAILABLE, which is not the same as "no
        # day is AVAILABLE". An out-of-enum value folds to UNRECOGNIZED, which is
        # neither, so a row whose monday is 2 does not qualify. Measured: the jar
        # reports nothing for such a row and we reported this notice.
        # An absent value reads as the enum's first constant, which is
        # NOT_AVAILABLE; in practice the column is required, so a missing one
        # draws missing_required_field and the row never reaches a rule.
        if any((row.get(name) or NOT_AVAILABLE) != NOT_AVAILABLE for name in WEEKDAY_FIELDS):
            continue
        yield Notice(
            "service_has_no_active_day_of_the_week",
            Severity.WARNING,
            {"csvRowNumber": row["_row_number"], "serviceId": row["service_id"]},
        )
