"""Feed builders for `pathway_unreachable_location`'s two test modules.

Shared rather than copied because the tests split in two once they passed the file-size limit: what
the traversal reaches, and which locations are in scope for reporting. Both halves build the same
station, and a builder that drifted between them would have the two halves testing different rules.

The station is the shape every probe varies: one station, one entrance, two platforms, with a
bidirectional pathway keeping P1 reachable so that the notice under test is always about P2.
"""

from __future__ import annotations

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CODE = "pathway_unreachable_location"
CTX = Context(date=datetime.date(2026, 7, 1), country_code="US")

PLATFORM = 0
STATION = 1
ENTRANCE = 2
GENERIC_NODE = 3
BOARDING_AREA = 4


def stop(number, stop_id, name, location_type=None, parent=None):
    """A stops.txt row. `location_type=None` means the column was blank, which is a platform."""
    row = {"_row_number": number, "stop_id": stop_id, "stop_name": name}
    if location_type is not None:
        row["location_type"] = location_type
    if parent is not None:
        row["parent_station"] = parent
    return row


def pathway(number, source, target, bidirectional=0):
    return {
        "_row_number": number,
        "pathway_id": f"W{number}",
        "from_stop_id": source,
        "to_stop_id": target,
        "pathway_mode": 1,
        "is_bidirectional": bidirectional,
    }


BASE_STOPS = [
    stop(2, "ST", "Station", STATION),
    stop(3, "EN", "Entrance", ENTRANCE, "ST"),
    stop(4, "P1", "Platform One", PLATFORM, "ST"),
    stop(5, "P2", "Platform Two", PLATFORM, "ST"),
]
# The pathway that keeps P1 reachable in every probe, so the notice under test is about P2.
P1_BOTH_WAYS = pathway(2, "EN", "P1", bidirectional=1)


def fire(stops, pathways):
    registry.load_rules()
    view = FakeFeed({"stops.txt": stops, "pathways.txt": pathways})
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(view, CTX)]


def reported_ids(stops, pathways):
    return [row["stopId"] for row in fire(stops, pathways)]
