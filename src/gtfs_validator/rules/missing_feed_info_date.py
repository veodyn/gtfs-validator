"""FeedServiceDateValidator: feed_info's two dates come as a pair."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule


@rule(code="missing_feed_info_date", severity=Severity.WARNING, filename="feed_info.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    has_start = row.get("feed_start_date") is not None
    has_end = row.get("feed_end_date") is not None
    # An exclusive or: neither present is fine and both present is fine.
    if has_start == has_end:
        return
    yield Notice(
        "missing_feed_info_date",
        Severity.WARNING,
        {
            "csvRowNumber": row["_row_number"],
            "fieldName": "feed_end_date" if has_start else "feed_start_date",
        },
    )
