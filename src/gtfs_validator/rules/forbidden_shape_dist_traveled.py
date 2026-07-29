"""StopTimesShapeDistTraveledPresenceValidator: a distance on a zone, not a stop.

A `shape_dist_traveled` measures progress along a shape, which a location group or
GeoJSON location has no position on, so carrying one is an error. Only rows with **no**
`stop_id` are considered: a real stop may carry a distance freely.

A file rule despite upstream being a `SingleEntityValidator`, because
`shouldCallValidate` is an **AND** of two header conditions here, needing
`shape_dist_traveled` *and* one of `location_id` / `location_group_id`, and the
registry's `requires_any_column` only expresses "any of". The two rule kinds are
behaviourally equivalent for this check, since both already see nothing from a table
whose load failed.

Measured: on a trip whose second stop time names a location group and a distance, the
jar reports that row with `locationId` as `""` rather than dropping the key, and says
nothing about a normal stop carrying a distance or a location group without one.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule, scan_rule

STOP_TIMES = "stop_times.txt"
DISTANCE = "shape_dist_traveled"
ZONE_COLUMNS = ("location_id", "location_group_id")


class _Consumer:
    def row(self, row: dict) -> list[Notice] | None:
        if row.get("stop_id") is not None:
            return None
        if row.get("location_group_id") is None and row.get("location_id") is None:
            return None
        distance = row.get(DISTANCE)
        if distance is None:
            return None
        return [
            Notice(
                "forbidden_shape_dist_traveled",
                Severity.ERROR,
                {
                    "csvRowNumber": row["_row_number"],
                    "tripId": row.get("trip_id"),
                    # Absent strings render as the generated entity's default, which is
                    # the fourth time this has come up: see attributionId and stopName.
                    "locationGroupId": row.get("location_group_id") or "",
                    "locationId": row.get("location_id") or "",
                    "shapeDistTraveled": distance,
                },
            )
        ]

    def finish(self) -> Iterator[Notice]:
        return iter(())


@scan_rule(code="forbidden_shape_dist_traveled", table=STOP_TIMES)
def scan(feed, ctx: Context) -> _Consumer | None:
    """The hub factory: None unless the header carries a distance and a zone column."""
    if not feed.has_column(STOP_TIMES, DISTANCE):
        return None
    if not any(feed.has_column(STOP_TIMES, column) for column in ZONE_COLUMNS):
        return None
    return _Consumer()


@file_rule(code="forbidden_shape_dist_traveled", severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    """The sequential path, on the same consumer the hub feeds."""
    consumer = scan(feed, ctx)
    if consumer is None:
        return
    for row in feed.rows(STOP_TIMES):
        yield from consumer.row(row) or ()
    yield from consumer.finish()
