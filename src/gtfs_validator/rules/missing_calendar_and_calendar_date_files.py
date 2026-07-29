"""MissingCalendarAndCalendarDateValidator: a feed needs one of the two files."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule


@file_rule(code="missing_calendar_and_calendar_date_files", severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # isMissingFile, not isEmpty. Measured: a feed whose calendar.txt is present
    # but header-only draws nothing, so an empty table suppresses this notice
    # exactly as a populated one does.
    if feed.is_missing("calendar.txt") and feed.is_missing("calendar_dates.txt"):
        yield Notice("missing_calendar_and_calendar_date_files", Severity.ERROR, {})
