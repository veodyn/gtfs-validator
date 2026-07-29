"""InconsistentRouteTypeForBlockIdValidator: one block, two kinds of vehicle.

A block is a vehicle's day of work, so every trip in it should be the same mode. Trips of a bus
route and a rail route sharing a block describe a bus that becomes a train.

Both list fields are `", "`-joined **strings**, not arrays, and the types are enum *names*:
measured as `"R_BUS, R_RAIL"` and `"BUS, RAIL"`. Each list is de-duplicated in trip order, so a
block whose three trips use two routes names two.

A trip whose route does not exist contributes no type, so a block of one real route and one broken
reference is consistent here and the broken reference is foreign_key_violation's to report.

Upstream iterates a Guava multimap, whose `asMap()` is backed by a HashMap keyed by block_id, so
the notices come out in bucket order. That decides which thousand a capped report keeps: measured on
1,005 inconsistent blocks, where the jar's samples include B1000 to B1004 and file order keeps
B0086 onwards.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import multimap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.enums import enum_name
from gtfs_validator.rules.registry import file_rule

CODE = "inconsistent_route_type_for_block_id"
TRIPS = "trips.txt"
ROUTES = "routes.txt"
BLOCK_ID = "block_id"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # A header test, as upstream's shouldCallValidate is: a feed without block_id is silent.
    if not feed.has_column(TRIPS, BLOCK_ID) or feed.dependency_failed(ROUTES):
        return
    route_types = {
        row["route_id"]: row.get("route_type")
        for row in feed.rows(ROUTES)
        if row.get("route_id") is not None
    }

    blocks: dict[str, tuple[list[str], list[int]]] = {}
    for trip in feed.rows(TRIPS):
        block_id = trip.get(BLOCK_ID)
        if not block_id:
            continue
        route_ids, types = blocks.setdefault(block_id, ([], []))
        route_id = trip.get("route_id")
        if route_id is not None and route_id not in route_ids:
            route_ids.append(route_id)
        if route_id in route_types:
            route_type = route_types[route_id]
            if route_type not in types:
                types.append(route_type)

    for block_id in multimap_order(blocks):
        route_ids, types = blocks[block_id]
        if len(types) < 2:
            continue
        yield Notice(
            CODE,
            Severity.WARNING,
            {
                "blockId": block_id,
                "routeIds": ", ".join(route_ids),
                "routeTypes": ", ".join(
                    enum_name(ROUTES, "route_type", value) or "" for value in types
                ),
            },
        )
