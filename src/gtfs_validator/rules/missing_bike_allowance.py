"""BikesAllowanceValidator: a ferry trip that does not say whether bikes fit.

Only ferry routes, and only trips whose bikes_allowed is UNKNOWN or UNRECOGNIZED.
Measured: on a ferry route with trips leaving the field blank, setting it to 0, to 1,
to 2 and to an out-of-enum 9, the jar reports the blank, the 0 and the 9, and says
nothing about a bus route's trips.

The out-of-enum case only lands here because plan 4 made the store fold such a value
to the enum's UNRECOGNIZED number rather than keeping the raw 9. Keeping the raw
value would have missed that trip.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule

# GtfsRouteType.FERRY.
FERRY = 4
# GtfsBikesAllowed.UNKNOWN, which is also the default an absent value reads as, and
# UNRECOGNIZED, which is min(0, *values) - 1 for this enum.
UNKNOWN = 0
UNRECOGNIZED = -1


@file_rule(code="missing_bike_allowance", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # Upstream iterates routeTable.byRouteType(FERRY) and then byRouteId per
    # route, so notices come out grouped by route in routes.txt file order, not
    # in trips.txt file order. Which 1,000 samples survive the export cap
    # depends on that; measured on the 904-AE corpus feed, whose ferry trips
    # interleave routes and pass the cap. byRouteType is a secondary index, so
    # unlike the primary-key map it lists a duplicated route id once per row.
    ferries = [
        row["route_id"]
        for row in feed.rows("routes.txt")
        if row.get("route_id") is not None and row.get("route_type") == FERRY
    ]
    for route_id in ferries:
        for trip in feed.rows_where("trips.txt", "route_id", route_id):
            # An absent value reads as the enum's first constant, which is UNKNOWN.
            if (trip.get("bikes_allowed") or UNKNOWN) not in (UNKNOWN, UNRECOGNIZED):
                continue
            yield Notice(
                "missing_bike_allowance",
                Severity.WARNING,
                {
                    "csvRowNumber": trip["_row_number"],
                    "routeId": route_id,
                    "tripId": trip.get("trip_id"),
                },
            )
