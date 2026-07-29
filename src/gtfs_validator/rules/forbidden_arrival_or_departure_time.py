"""PickupDropOffWindowValidator, first branch: a fixed time on a flex stop time.

A pickup/drop-off window says a vehicle serves a place during a period; an arrival or
departure time says it is there at an instant. A stop time cannot mean both, so any row
carrying a window and either time is reported.

Half a window is enough to trigger the check, and the notice carries only the values the row
actually has: upstream passes an explicit `null` for each absent one and gson drops it. So a
row with an arrival and a start window produces a three-key context, where the two
PickupDropOffType notices next door would pad the missing end with `"00:00:00"`.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import windows
from gtfs_validator.rules.registry import rule

CODE = "forbidden_arrival_or_departure_time"
STOP_TIMES = "stop_times.txt"
TIME_COLUMNS = ("arrival_time", "departure_time")


@rule(
    code=CODE,
    severity=Severity.ERROR,
    filename=STOP_TIMES,
    requires_any_column=windows.WINDOW_COLUMNS,
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if not windows.has_window(row):
        return
    if all(row.get(column) is None for column in TIME_COLUMNS):
        return
    yield Notice(
        CODE,
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            **windows.present_times(row, windows.TIME_FIELDS),
        },
    )
