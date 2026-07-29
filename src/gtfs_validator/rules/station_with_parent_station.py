"""LocationTypeSingleEntityValidator, first branch: a station inside something else.

Stations are the top of the hierarchy, so a parent_station on one is an error whatever
it points at. The reference is reported verbatim and is not resolved: a station whose
parent does not exist draws this notice as well as the broken reference.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import STATION, location_type_of
from gtfs_validator.rules.registry import rule


@rule(code="station_with_parent_station", severity=Severity.ERROR, filename="stops.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    parent = row.get("parent_station")
    # `hasParentStation()`. A station whose parent_station is present but empty *is*
    # reported, with `parentStation: ""`. Measured on `ps2`.
    if parent is None or location_type_of(row) != STATION:
        return
    yield Notice(
        "station_with_parent_station",
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            "stopId": row.get("stop_id") or "",
            "stopName": row.get("stop_name") or "",
            "parentStation": parent,
        },
    )
