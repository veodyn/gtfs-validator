"""StopRequiredLocationValidator: a stop, station or entrance with no coordinates.

`hasStopLatLon` needs **both**, so a row carrying only a latitude is reported.
Measured: rows for a stop, a station and an entrance with neither coordinate are
reported, a generic node and a boarding area are not, and a stop with only a
latitude is.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.enums import enum_name
from gtfs_validator.rules.registry import rule

# The same three location types missing_stop_name covers. location_type is optional
# and defaults to 0, so a blank one is a stop.
LOCATED_TYPES = (0, 1, 2)
DEFAULT_LOCATION_TYPE = 0


@rule(code="stop_without_location", severity=Severity.ERROR, filename="stops.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    location_type = row.get("location_type")
    if location_type is None:
        location_type = DEFAULT_LOCATION_TYPE
    if location_type not in LOCATED_TYPES:
        return
    if row.get("stop_lat") is not None and row.get("stop_lon") is not None:
        return
    yield Notice(
        "stop_without_location",
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            "locationType": enum_name("stops.txt", "location_type", location_type),
            "stopId": row.get("stop_id"),
        },
    )
