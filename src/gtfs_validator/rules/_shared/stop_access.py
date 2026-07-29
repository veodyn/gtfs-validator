"""The two StopAccessValidator branches, which are opposites of each other.

`stop_access` says whether a place is reached through the station's pathway graph, so it only means
anything for a platform inside a station. Two ways to get it wrong, and they are mutually exclusive:

- a platform that has no parent station, so there is no graph for the answer to be about;
- anything that is not a platform, where the field does not apply at all.

Both notices carry the same five fields, with `stopAccess` and `locationType` as enum **names**.
Gated on stops.txt declaring the column, which is a header test rather than a value test.
"""

from __future__ import annotations

from gtfs_validator.rules._shared.enums import enum_name

STOPS = "stops.txt"
STOP_ACCESS = "stop_access"


def context_for(row: dict, location_type: int) -> dict:
    return {
        "csvRowNumber": row["_row_number"],
        "stopId": row.get("stop_id") or "",
        "stopName": row.get("stop_name") or "",
        "stopAccess": enum_name(STOPS, STOP_ACCESS, row.get(STOP_ACCESS)) or "",
        "locationType": enum_name(STOPS, "location_type", location_type) or "",
    }
