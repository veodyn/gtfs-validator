"""RouteNameValidator, fourth branch: a description that repeats a name.

The short-name branch returns rather than falling through, so a route whose
description equals both names draws one notice naming route_short_name. Keeping
both branches in one module is what preserves that; splitting them on
specifiedField would emit two.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javatext import equals_ignore_case
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule


def _report(row: dict, field_name: str) -> Notice:
    return Notice(
        "same_name_and_description_for_route",
        Severity.WARNING,
        {
            "csvRowNumber": row["_row_number"],
            "routeId": row["route_id"],
            "routeDesc": row["route_desc"],
            "specifiedField": field_name,
        },
    )


@rule(
    code="same_name_and_description_for_route",
    severity=Severity.WARNING,
    filename="routes.txt",
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    description = row.get("route_desc")
    if description is None:
        return
    short_name = row.get("route_short_name")
    long_name = row.get("route_long_name")
    # equalsIgnoreCase, not casefold equality. Measured: a description of
    # "STRASSE" is reported against a short name of "Strasse" and not against the
    # sharp-s spelling, whose length in code units differs.
    if short_name is not None and equals_ignore_case(description, short_name):
        yield _report(row, "route_short_name")
        return
    if long_name is not None and equals_ignore_case(description, long_name):
        yield _report(row, "route_long_name")
