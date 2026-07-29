"""PickupDropOffTypeValidator, second branch: a window with a regular drop-off.

Narrower than its sibling: only REGULAR contradicts a window here, where the pickup
branch also rejects ON_REQUEST_TO_DRIVER. Measured, and the asymmetry is upstream's.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.windows import WINDOW_COLUMNS, has_window, window_context
from gtfs_validator.rules.registry import rule

# GtfsPickupDropOff.REGULAR, which is also the default for an absent value.
REGULAR = 0


@rule(
    code="forbidden_drop_off_type",
    severity=Severity.ERROR,
    filename="stop_times.txt",
    requires_any_column=WINDOW_COLUMNS,
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if not has_window(row):
        return
    if (row.get("drop_off_type") or REGULAR) != REGULAR:
        return
    yield Notice(
        "forbidden_drop_off_type",
        Severity.ERROR,
        {"csvRowNumber": row["_row_number"], **window_context(row)},
    )
