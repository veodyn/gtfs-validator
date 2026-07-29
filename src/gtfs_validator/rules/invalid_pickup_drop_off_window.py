"""PickupDropOffWindowValidator, third branch: a window that ends before it starts.

The end must be *strictly* later than the start, so a zero-length window is reported as well
as an inverted one. Both times are compared as the seconds `GtfsTime` holds, which run past
86,400: a window from 08:00:00 to 25:30:00 is valid and stays valid, where comparing wrapped
clock times would report it.

Only reached when both ends are present, since the missing-window branch returns first.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import windows
from gtfs_validator.rules.registry import rule

CODE = "invalid_pickup_drop_off_window"
STOP_TIMES = "stop_times.txt"


@rule(
    code=CODE,
    severity=Severity.ERROR,
    filename=STOP_TIMES,
    requires_any_column=windows.WINDOW_COLUMNS,
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if not windows.has_both_windows(row):
        return
    if row[windows.START_WINDOW] < row[windows.END_WINDOW]:
        return
    yield Notice(
        CODE,
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            **windows.present_times(row, windows.WINDOW_FIELDS),
        },
    )
