"""PickupDropOffTypeValidator, first branch: a window with a bookable pickup.

A stop time with a pickup/drop-off window is demand-responsive, so a pickup_type of
REGULAR or ON_REQUEST_TO_DRIVER contradicts it. Both types default to REGULAR when
absent, so a windowed row that omits pickup_type fires too.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.windows import WINDOW_COLUMNS, has_window, window_context
from gtfs_validator.rules.registry import rule

# GtfsPickupDropOff.REGULAR and ON_REQUEST_TO_DRIVER.
REGULAR = 0
ON_REQUEST_TO_DRIVER = 3
FORBIDDEN_PICKUP_TYPES = (REGULAR, ON_REQUEST_TO_DRIVER)


@rule(
    code="forbidden_pickup_type",
    severity=Severity.ERROR,
    filename="stop_times.txt",
    requires_any_column=WINDOW_COLUMNS,
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if not has_window(row):
        return
    if (row.get("pickup_type") or REGULAR) not in FORBIDDEN_PICKUP_TYPES:
        return
    yield Notice(
        "forbidden_pickup_type",
        Severity.ERROR,
        {"csvRowNumber": row["_row_number"], **window_context(row)},
    )
