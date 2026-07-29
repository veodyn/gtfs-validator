"""missing_bike_allowance emission order, which decides cap survivorship.

BikesAllowanceValidator iterates `routeTable.byRouteType(FERRY)` and then
`tripTable.byRouteId(...)` per route, so notices come out grouped by route in
routes.txt file order, not in trips.txt file order. Below the export cap the
sorted report hides the difference; above it, which 1,000 samples survive
depends on it, which is how the 904-AE corpus feed (interleaved ferry trips,
more than 1,000 notices) caught it.
"""

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 6, 1), country_code="US")
FERRY = 4


def test_notices_group_by_route_in_routes_file_order():
    tables = {
        "routes.txt": [
            {"route_id": "F1", "route_type": FERRY, "_row_number": 2},
            {"route_id": "F2", "route_type": FERRY, "_row_number": 3},
        ],
        "trips.txt": [
            {"route_id": "F2", "trip_id": "T1", "bikes_allowed": None, "_row_number": 2},
            {"route_id": "F1", "trip_id": "T2", "bikes_allowed": None, "_row_number": 3},
            {"route_id": "F2", "trip_id": "T3", "bikes_allowed": None, "_row_number": 4},
            {"route_id": "F1", "trip_id": "T4", "bikes_allowed": None, "_row_number": 5},
        ],
    }
    registry.load_rules()
    notices = list(registry.FILE_REGISTRY["missing_bike_allowance"].func(FakeFeed(tables), CTX))
    assert [n.context["tripId"] for n in notices] == ["T2", "T4", "T1", "T3"]
