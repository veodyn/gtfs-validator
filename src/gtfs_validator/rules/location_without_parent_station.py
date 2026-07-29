"""LocationTypeSingleEntityValidator, third branch: entrances, nodes, boarding areas.

These three types are meaningless outside a station, so a missing parent_station is an
error. The notice carries `locationTypeValue()`, the raw integer rather than the enum
name, measured as 2, 3 and 4 on the three types.

Reading the raw value matters for an out-of-enum location_type: the store folds it to
UNRECOGNIZED, which is not one of these three, so such a row falls through here
exactly as upstream's switch does.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import REQUIRES_PARENT, location_type_of
from gtfs_validator.rules.registry import rule


@rule(code="location_without_parent_station", severity=Severity.ERROR, filename="stops.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    location_type = location_type_of(row)
    # `hasParentStation()`. Same branch as the platform rule and the same fix: an empty
    # parent_station is present, so the chain stops before reaching this.
    if row.get("parent_station") is not None or location_type not in REQUIRES_PARENT:
        return
    yield Notice(
        "location_without_parent_station",
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            "stopId": row.get("stop_id") or "",
            "stopName": row.get("stop_name") or "",
            "locationType": location_type,
        },
    )
