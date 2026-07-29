"""Feed builders for TripHeadsignValidator's two test modules.

Shared rather than copied because the rule's tests split in two once they passed the file-size
limit: what the scan does, and what counts as a present field. Both halves build the same three
tables, and a builder that drifts between them would have the two halves testing different rules.

`name=None` on a stop, and `headsign=None` on a trip, mean the cell was missing or empty. `""`
means a cell that was present and trimmed to nothing, which is a *different* state; see
`test_rules_trip_headsign_presence`.
"""

from __future__ import annotations

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CODE = "trip_headsign_matches_intermediate_stop"
CTX = Context(date=datetime.date(2026, 6, 1), country_code="US")


def trip(number, trip_id, headsign):
    return {
        "_row_number": number,
        "trip_id": trip_id,
        "route_id": "R1",
        "service_id": "WEEK",
        "trip_headsign": headsign,
    }


def stop_times(trip_id, *stop_ids):
    """One stop time per id, numbered from row 2 and sequenced from 1."""
    return [
        {
            "_row_number": 2 + index,
            "trip_id": trip_id,
            "stop_id": stop_id,
            "stop_sequence": index + 1,
        }
        for index, stop_id in enumerate(stop_ids)
    ]


def stop(stop_id, name):
    return {"_row_number": 2, "stop_id": stop_id, "stop_name": name}


STOPS = [stop("A", "Alpha"), stop("B", "Beta"), stop("C", "Gamma")]


def fire(trips, times, stops=None):
    registry.load_rules()
    view = FakeFeed(
        {
            "trips.txt": trips,
            "stop_times.txt": times,
            "stops.txt": stops if stops is not None else STOPS,
        }
    )
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(view, CTX)]
