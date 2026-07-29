"""TransfersTripReferenceValidator: a transfer naming a trip and a route that disagree.

`expectedRouteId` is the route the *trip* actually runs on, and `routeId` is what the transfer
claims. Measured: a transfer whose from_trip_id is on R1 while its from_route_id says R2 reports
routeId R2 and expectedRouteId R1.

The route test and the stop test are independent, so one transfer end can draw this and
`transfer_with_invalid_trip_and_stop` at once.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.transfer_trips import trip_references
from gtfs_validator.rules.registry import file_rule

CODE = "transfer_with_invalid_trip_and_route"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for row, direction, trip in trip_references(feed):
        route_id = row.get(direction.route_field)
        if route_id is None or trip.get("route_id") == route_id:
            continue
        yield Notice(
            CODE,
            Severity.ERROR,
            {
                "csvRowNumber": row["_row_number"],
                "tripFieldName": direction.trip_field,
                "tripId": row[direction.trip_field],
                "routeFieldName": direction.route_field,
                "routeId": route_id,
                "expectedRouteId": trip.get("route_id"),
            },
        )
