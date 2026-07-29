"""Feed builders for OverlappingPickupDropOffZoneValidator.

Shared rather than copied, for the reason `fasttravel.py` and `blockoverlap.py` are: the rule
reads a flex `stop_times.txt` and a `locations.geojson`, and a test that builds both by hand is
mostly scaffolding.
"""

from __future__ import annotations

import datetime
import json

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CODE = "overlapping_zone_and_pickup_drop_off_window"
CTX = Context(date=datetime.date(2026, 6, 1), country_code="US")

H8, H9, H10, H11, H12 = 28800, 32400, 36000, 39600, 43200
# GtfsPickupDropOff constants, as the store holds them: the enum's numbers.
PHONE_AGENCY = 2
COORDINATE_DRIVER = 3


def square(x, y, size):
    return [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]]


def feature(index, feature_id, rings):
    return {
        "_row_number": index,
        "feature_index": index,
        "feature_id": feature_id,
        "geometry_type": "Polygon",
        "coordinates": json.dumps(rings),
    }


# The probe's zones. L1 and L2 properly overlap; L3 sits wholly inside L1; L4 shares one edge
# with L1; L5 is far away; L6 is L1 exactly.
ZONES = [
    feature(0, "L1", square(0.0, 0.0, 1.0)),
    feature(1, "L2", square(0.5, 0.5, 1.0)),
    feature(2, "L3", square(0.25, 0.25, 0.25)),
    feature(3, "L4", square(1.0, 0.0, 1.0)),
    feature(4, "L5", square(10.0, 10.0, 1.0)),
    feature(5, "L6", square(0.0, 0.0, 1.0)),
]


def stop_time(
    row, trip_id, sequence, location_id, start, end, pickup=PHONE_AGENCY, drop_off=COORDINATE_DRIVER
):
    return {
        "_row_number": row,
        "trip_id": trip_id,
        "stop_sequence": sequence,
        "location_id": location_id,
        "start_pickup_drop_off_window": start,
        "end_pickup_drop_off_window": end,
        "pickup_type": pickup,
        "drop_off_type": drop_off,
    }


def fire(rows, *, zones=None, unindexable=frozenset()):
    registry.load_rules()
    view = FakeFeed(
        {
            "stop_times.txt": rows,
            "locations.geojson": ZONES if zones is None else zones,
        },
        unindexable=unindexable,
    )
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(view, CTX)]


