"""GtfsLocationType constants and the parent-station requirement.

location_type is optional and defaults to STOP, so `row.get(...) or STOP` is the
correct read: a blank cell is a stop, not an unknown type.

`requiresParentStation` covers exactly the three types that cannot stand alone.
STATION is the opposite case, forbidden from having one, and STOP is conditional on
platform_code.
"""

from __future__ import annotations

STOP = 0
STATION = 1
ENTRANCE = 2
GENERIC_NODE = 3
BOARDING_AREA = 4

REQUIRES_PARENT = frozenset({ENTRANCE, GENERIC_NODE, BOARDING_AREA})


def location_type_of(row: dict) -> int:
    return row.get("location_type") or STOP
