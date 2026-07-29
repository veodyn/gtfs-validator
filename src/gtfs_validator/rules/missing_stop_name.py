"""StopNameValidator, first branch: stops, stations and entrances need a name.

The whole validator is skipped when the header carries neither stop_name nor
location_type, which is a header test rather than a value test: a present but
empty stop_name column still runs the check.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.enums import enum_name
from gtfs_validator.rules.registry import rule

# GtfsLocationType numbers. location_type is optional and defaults to 0, so a row
# with no value is a stop rather than an exempt location: the jar reports the
# row that leaves the column blank.
NAMED_LOCATION_TYPES = (0, 1, 2)
DEFAULT_LOCATION_TYPE = 0


@rule(
    code="missing_stop_name",
    severity=Severity.ERROR,
    filename="stops.txt",
    requires_any_column=("stop_name", "location_type"),
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    location_type = row.get("location_type")
    if location_type is None:
        location_type = DEFAULT_LOCATION_TYPE
    if location_type not in NAMED_LOCATION_TYPES:
        return
    if row.get("stop_name"):
        return
    yield Notice(
        "missing_stop_name",
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            "locationType": enum_name("stops.txt", "location_type", location_type),
            "stopId": row["stop_id"],
        },
    )
