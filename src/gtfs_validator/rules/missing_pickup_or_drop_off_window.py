"""PickupDropOffWindowValidator, second branch: half a pickup/drop-off window.

The two window fields are meaningful only as a pair, so a row carrying one is reported and
the notice names the one it has. The absent one is passed as an explicit `null` and dropped
by gson, which is why this context has one key rather than two.

Upstream returns after this notice, so a half window never also draws
`invalid_pickup_drop_off_window`: the ordering check compares two times, and only one exists.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import windows
from gtfs_validator.rules.registry import rule

CODE = "missing_pickup_or_drop_off_window"
STOP_TIMES = "stop_times.txt"


@rule(
    code=CODE,
    severity=Severity.ERROR,
    filename=STOP_TIMES,
    requires_any_column=windows.WINDOW_COLUMNS,
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if not windows.has_window(row) or windows.has_both_windows(row):
        return
    yield Notice(
        CODE,
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            **windows.present_times(row, windows.WINDOW_FIELDS),
        },
    )
