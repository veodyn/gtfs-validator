"""RouteNameValidator, first branch: a route needs at least one name."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule


@rule(
    code="route_both_short_and_long_name_missing",
    severity=Severity.ERROR,
    filename="routes.txt",
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if row.get("route_short_name") is None and row.get("route_long_name") is None:
        yield Notice(
            "route_both_short_and_long_name_missing",
            Severity.ERROR,
            {"routeId": row["route_id"], "csvRowNumber": row["_row_number"]},
        )
