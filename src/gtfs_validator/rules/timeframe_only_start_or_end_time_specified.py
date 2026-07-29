"""TimeframeStartAndEndTimeValidator, first branch: an exclusive or."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule


@rule(
    code="timeframe_only_start_or_end_time_specified",
    severity=Severity.ERROR,
    filename="timeframes.txt",
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    # hasStartTime() ^ hasEndTime(): a row with neither bound is fine, which is
    # why this is an exclusive or rather than a pair of presence checks.
    if (row.get("start_time") is None) == (row.get("end_time") is None):
        return
    yield Notice(
        "timeframe_only_start_or_end_time_specified",
        Severity.ERROR,
        {"csvRowNumber": row["_row_number"]},
    )
