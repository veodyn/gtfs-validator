"""DuplicateRouteNameValidator: two routes indistinguishable to a passenger.

A route is identified for this purpose by its long name, short name, type and agency, and the
notice pairs the *first* route holding that combination with each later one. So three identical
routes draw two notices, not one.

An unset name is part of the key as the empty string, not as an absence: two routes with no short
name and the same long name are duplicates, and the notice reports `routeShortName: ""`. Measured,
and the fourth instance of the type-default class in this codebase.

**Upstream keys on a 64-bit Guava hash of the four fields, and this keys on the fields themselves.**
`getRouteKey` feeds them through `putUnencodedChars`, separated by NUL, into a hash whose `asLong`
becomes the map key. A tuple is equivalent unless two *different* combinations collide in 64 bits,
which no feed will produce by accident: the alternative is porting Guava's hash function to compare
values it only ever compares for equality. Recorded here rather than left as a silent choice.

**Not measured:** a route_type outside the enum. Upstream keys on `routeType().getNumber()`, which
is -1 for anything unrecognised, so types 999 and 1000 would share a key while reporting different
`routeTypeValue`s. Our store folds out-of-enum values before a rule sees them, so the behaviour
here follows the store rather than a probe. Worth a feed if it ever matters.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule

CODE = "duplicate_route_name"
FILENAME = "routes.txt"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    first_seen: dict[tuple, dict] = {}
    for row in feed.rows(FILENAME):
        long_name = row.get("route_long_name") or ""
        short_name = row.get("route_short_name") or ""
        agency_id = row.get("agency_id") or ""
        route_type = row.get("route_type")
        key = (long_name, short_name, route_type, agency_id)
        # putIfAbsent, so the first route holding a key stays the one every later duplicate is
        # paired with rather than the immediately preceding one.
        previous = first_seen.setdefault(key, row)
        if previous is row:
            continue
        yield Notice(
            CODE,
            Severity.WARNING,
            {
                "csvRowNumber1": previous["_row_number"],
                "routeId1": previous.get("route_id"),
                "csvRowNumber2": row["_row_number"],
                "routeId2": row.get("route_id"),
                # Identical on both by construction: they are what made the two collide.
                "routeShortName": short_name,
                "routeLongName": long_name,
                "routeTypeValue": route_type,
                "agencyId": agency_id,
            },
        )
