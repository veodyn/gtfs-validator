"""UniqueGeographyIdValidator: one id naming two different kinds of geography.

Stops, location groups and GeoJSON features share one id space, because a stop time may name any of
them. The same id in two of those files is ambiguous; the same id twice in *one* file is a duplicate
key and this rule stays out of it, which is why the check is on the number of distinct **files**
rather than the number of entries.

The context names each file's position and **omits the field for a file that does not carry the id**,
measured: a stop sharing an id with a GeoJSON feature reports `csvRowNumberA` and `featureIndex` and
no `csvRowNumberB`. An id present in all three carries all three. So the fields are

    csvRowNumberA  stops.txt
    csvRowNumberB  location_groups.txt
    featureIndex   locations.geojson

and a notice carries two or three of them.

A blank id is reported like any other: a stop and a location group both carrying a whitespace-only id
draw one notice with `geographyId: ""`, measured, so this rule does not filter them.

Upstream reads `location_groups.txt` while naming `location_group_stops.txt` in the notice's file
list, which reads like a slip but changes nothing observable: the row number reported is the one from
location_groups.txt, measured.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import hashmap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule

CODE = "duplicate_geography_id"
STOPS = "stops.txt"
LOCATION_GROUPS = "location_groups.txt"
GEOJSON = "locations.geojson"

# (file, id column, context key). Order matters only for readability; the notice is keyed by name.
SOURCES = (
    (STOPS, "stop_id", "csvRowNumberA"),
    (LOCATION_GROUPS, "location_group_id", "csvRowNumberB"),
    (GEOJSON, "feature_id", "featureIndex"),
)


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    positions: dict[str, dict[str, int]] = {}
    for filename, id_column, key in SOURCES:
        for row in feed.rows(filename):
            identifier = row.get(id_column)
            if identifier is None:
                continue
            # A feature reports its index; a table row reports its line.
            position = row["feature_index"] if filename == GEOJSON else row["_row_number"]
            # First wins within a file, so a duplicate inside one file does not shadow the
            # cross-file position with a later one.
            positions.setdefault(identifier, {}).setdefault(key, position)

    # HashMap order, because upstream groups with Collectors.groupingBy and iterates the result.
    # Not exactly: groupingBy inserts through computeIfAbsent and its bucket arrangement differs
    # from a plain put, so on a 1,005-notice probe this retains 999 of the jar's 1,000 samples
    # where insertion order retained 995. Recorded in the HashMap-order audit rather than claimed
    # as exact.
    for identifier in hashmap_order(positions):
        found = positions[identifier]
        if len(found) < 2:
            continue
        yield Notice(CODE, Severity.ERROR, {"geographyId": identifier, **found})
