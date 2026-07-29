"""ParentStationValidator: a location whose parent is the wrong kind of place.

A platform, an entrance and a generic node all belong to a station; a boarding area belongs to a
platform. That last row is the reason this is a table rather than one comparison: the rule is not
"everything wants a station".

Three skips, each measured, and each leaving the case to a rule that owns it:

- A **station** is skipped before its parent is even looked at, because a station with a parent is
  `station_with_parent_station`'s notice.
- A parent that **does not exist** is skipped, leaving the broken reference to
  `foreign_key_violation`. Reporting a wrong type here would double-report it.
- A location whose own `location_type` is **outside the enum** has no expectation at all, since
  `expectedParentLocationType` returns UNRECOGNIZED and the guard tests for it. Measured on a
  location_type of 7 under a station, which draws nothing.

The location types are reported as **integers**, not enum names, which is the opposite of the
stop-access pair on the same file. Both were measured rather than assumed.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import (
    BOARDING_AREA,
    ENTRANCE,
    GENERIC_NODE,
    STATION,
    STOP,
    location_type_of,
)
from gtfs_validator.rules._shared.stop_coordinates import stops_by_id
from gtfs_validator.rules.registry import file_rule

CODE = "wrong_parent_location_type"
# expectedParentLocationType: everything but a boarding area belongs to a station.
EXPECTED_PARENT = {
    STOP: STATION,
    ENTRANCE: STATION,
    GENERIC_NODE: STATION,
    BOARDING_AREA: STOP,
}


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    stops = stops_by_id(feed)
    for row in feed.rows("stops.txt"):
        location_type = location_type_of(row)
        if location_type == STATION:
            continue
        # `!location.hasParentStation()`. An empty parent_station is present, and upstream
        # looks it up: a station stored under the empty id is a real parent to it.
        parent_id = row.get("parent_station")
        if parent_id is None:
            continue
        parent = stops.get(parent_id)
        if parent is None:
            continue
        expected = EXPECTED_PARENT.get(location_type)
        if expected is None:
            continue
        parent_type = location_type_of(parent)
        if parent_type == expected:
            continue
        yield Notice(
            CODE,
            Severity.ERROR,
            {
                "csvRowNumber": row["_row_number"],
                "stopId": row.get("stop_id"),
                # An unset String field reads as "" through its getter, so Gson writes an empty
                # string rather than omitting the key. Measured on `stopfeed`, whose stops carry
                # no stop_name: the jar sends "stopName": "" and passing None dropped the key.
                "stopName": row.get("stop_name") or "",
                "locationType": location_type,
                "parentCsvRowNumber": parent["_row_number"],
                "parentStation": parent_id,
                "parentStopName": parent.get("stop_name") or "",
                "parentLocationType": parent_type,
                "expectedLocationType": expected,
            },
        )
