"""InconsistentRouteTypeForInSeatTransferValidator: staying seated between two modes.

An in-seat transfer means the passenger does not leave the vehicle, so the two routes must be the
same mode. A bus route continuing as a rail route describes a vehicle that changes what it is.

Only `transfer_type` 4 qualifies: type 5, in-seat *not* allowed, is the statement that the transfer
is impossible and carries no expectation. Both routes must exist, so a transfer naming a route that
does not is skipped and left to foreign_key_violation.

The types report as enum **names**, measured as "BUS" and "RAIL" rather than 3 and 2.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.enums import enum_name
from gtfs_validator.rules.registry import file_rule

CODE = "inconsistent_route_type_for_in_seat_transfer"
TRANSFERS = "transfers.txt"
ROUTES = "routes.txt"

# GtfsTransferType.IN_SEAT_TRANSFER_ALLOWED.
IN_SEAT_ALLOWED = 4


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # First row wins for a duplicate route_id, as upstream's single-key index does: a route defined
    # as a bus and then again as rail is a bus here. Overwriting reported nothing where the jar
    # reports a mismatch.
    route_types: dict[str, object] = {}
    for row in feed.rows(ROUTES):
        route_id = row.get("route_id")
        if route_id is not None:
            route_types.setdefault(route_id, row.get("route_type"))
    for transfer in feed.rows(TRANSFERS):
        if transfer.get("transfer_type") != IN_SEAT_ALLOWED:
            continue
        from_route = transfer.get("from_route_id")
        to_route = transfer.get("to_route_id")
        if from_route not in route_types or to_route not in route_types:
            continue
        from_type, to_type = route_types[from_route], route_types[to_route]
        if from_type == to_type:
            continue
        yield Notice(
            CODE,
            Severity.WARNING,
            {
                "csvRowNumber": transfer["_row_number"],
                "fromRouteId": from_route,
                "toRouteId": to_route,
                "fromRouteType": enum_name(ROUTES, "route_type", from_type) or "",
                "toRouteType": enum_name(ROUTES, "route_type", to_type) or "",
            },
        )
