"""LocationTypeSingleEntityValidator, second branch: a platform with no station.

A stop only counts as a platform when it carries a platform_code, so this is INFO
rather than an error: a plain stop outside any station is ordinary, a stop that calls
itself platform "A" of nothing is a modelling slip.

Upstream tests `platformCode().isEmpty()` against the String default, so a
present-but-blank platform_code reads the same as an absent one.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import STOP, location_type_of
from gtfs_validator.rules.registry import rule


@rule(code="platform_without_parent_station", severity=Severity.INFO, filename="stops.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    # `hasParentStation()`, so `is not None`: an empty parent_station is present and takes
    # upstream's first branch, which means this else-if never runs. Truthiness reported a
    # platform the jar is silent about. Measured on `ps2`.
    if row.get("parent_station") is not None or location_type_of(row) != STOP:
        return
    if not row.get("platform_code"):
        return
    yield Notice(
        "platform_without_parent_station",
        Severity.INFO,
        {
            "csvRowNumber": row["_row_number"],
            "stopId": row.get("stop_id") or "",
            "stopName": row.get("stop_name") or "",
        },
    )
