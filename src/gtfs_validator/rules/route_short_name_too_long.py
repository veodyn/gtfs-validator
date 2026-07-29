"""RouteNameValidator, second branch: MAX_SHORT_NAME_LENGTH is 12."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javatext import utf16_length
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule

MAX_SHORT_NAME_LENGTH = 12


@rule(code="route_short_name_too_long", severity=Severity.WARNING, filename="routes.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    short_name = row.get("route_short_name")
    # String.length() counts UTF-16 units, so an astral character counts twice.
    # Measured: a short name of seven astral characters is 14 units and the jar
    # reports it, while len() sees 7 and would let it through.
    if short_name is not None and utf16_length(short_name) > MAX_SHORT_NAME_LENGTH:
        yield Notice(
            "route_short_name_too_long",
            Severity.WARNING,
            {
                "routeId": row["route_id"],
                "csvRowNumber": row["_row_number"],
                "routeShortName": short_name,
            },
        )
