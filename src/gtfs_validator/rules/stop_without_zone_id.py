"""StopZoneIdValidator: a stop with no zone_id on a route whose fares are zone-based.

A zone_id only matters when some fare rule actually uses zones, so the whole check is gated on
that: if no row of fare_rules.txt sets origin_id, destination_id or contains_id, nothing is
reported however many stops lack a zone. An absent or empty fare_rules.txt is the same gate.

Past the gate, the question is per stop and it is about *that stop's* routes. A stop is reported
when some trip calling at it belongs to a route that a zone-using fare rule names. So two stops
with no zone_id can differ: the one on the zoned route is reported and the one on the flat-fare
route is not. Measured on `zoneids`, where only the first draws the notice.

Two skips: a location that is not a platform, since a station has no fare zone of its own, and a
stop no trip serves, which upstream reaches through an empty route set rather than a special case.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import STOP, location_type_of
from gtfs_validator.rules.registry import file_rule

CODE = "stop_without_zone_id"
FARE_RULES = "fare_rules.txt"
ZONE_FIELDS = ("origin_id", "destination_id", "contains_id")


@file_rule(code=CODE, severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    zoned_routes = set()
    uses_zones = False
    for rule in feed.rows(FARE_RULES):
        if not any(rule.get(field) is not None for field in ZONE_FIELDS):
            continue
        uses_zones = True
        # route_id is optional in fare_rules.txt, and upstream keys the multimap on whatever the
        # getter returns, so a rule with no route contributes the empty string rather than nothing.
        zoned_routes.add(rule.get("route_id") or "")
    if not uses_zones:
        return

    routes_by_trip = {
        row.get("trip_id"): row.get("route_id") or "" for row in feed.rows("trips.txt")
    }
    routes_by_stop: dict[str, set[str]] = {}
    for stop_time in feed.rows("stop_times.txt"):
        stop_id, trip_id = stop_time.get("stop_id"), stop_time.get("trip_id")
        if stop_id is None or trip_id not in routes_by_trip:
            continue
        routes_by_stop.setdefault(stop_id, set()).add(routes_by_trip[trip_id])

    for row in feed.rows("stops.txt"):
        if location_type_of(row) != STOP or row.get("zone_id") is not None:
            continue
        stop_id = row.get("stop_id")
        if not routes_by_stop.get(stop_id, set()) & zoned_routes:
            continue
        yield Notice(
            CODE,
            Severity.INFO,
            {
                "stopId": stop_id,
                "stopName": row.get("stop_name") or "",
                "csvRowNumber": row["_row_number"],
            },
        )
