"""TimeframeStartAndEndTimeValidator, second branch: bounds cap at 24 hours.

Both bounds are checked independently, so a row past the cap on both draws two
notices, start_time first.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.render import hhmmss
from gtfs_validator.rules.registry import rule

TWENTY_FOUR_HOURS = 24 * 3600


@rule(
    code="timeframe_start_or_end_time_greater_than_twenty_four_hours",
    severity=Severity.ERROR,
    filename="timeframes.txt",
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    for field_name in ("start_time", "end_time"):
        value = row.get(field_name)
        # isAfter, so exactly 24:00:00 passes.
        if value is None or value <= TWENTY_FOUR_HOURS:
            continue
        yield Notice(
            "timeframe_start_or_end_time_greater_than_twenty_four_hours",
            Severity.ERROR,
            {
                "csvRowNumber": row["_row_number"],
                "fieldName": field_name,
                "time": hhmmss(value),
            },
        )
