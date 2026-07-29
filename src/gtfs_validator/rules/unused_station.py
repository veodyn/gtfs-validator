"""ParentStationValidator, first branch: a station with no platform under it.

Only a child of location_type STOP counts. Measured: a station whose only child is
an *entrance* is still reported, so this is not "a station nobody references" but
"a station no platform belongs to".

A child naming a parent that does not exist is skipped here; the broken reference is
another rule's to report.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import hashmap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule

# GtfsLocationType.STOP and STATION. location_type is optional and defaults to 0,
# so a child leaving it blank is a stop.
STOP = 0
STATION = 1


@file_rule(code="unused_station", severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    stations: dict[str, dict] = {}
    parents_of_stops: set[str] = set()
    known: set[str] = set()
    for row in feed.rows("stops.txt"):
        stop_id = row.get("stop_id")
        if stop_id is None:
            continue
        known.add(stop_id)
        if (row.get("location_type") or STOP) == STATION:
            # A station's own parent_station is another rule's problem.
            stations[stop_id] = row
            continue
        parent = row.get("parent_station")
        if parent is not None and (row.get("location_type") or STOP) == STOP:
            parents_of_stops.add(parent)

    # HashSet order upstream, which decides which thousand a capped report keeps:
    # measured on 1,005 childless stations, whose samples begin ST0160.
    for stop_id in hashmap_order(stations):
        row = stations[stop_id]
        # A child pointing at a missing parent never lands in parents_of_stops, and a
        # station is only excused by a child that actually exists.
        if stop_id in parents_of_stops and stop_id in known:
            continue
        yield Notice(
            "unused_station",
            Severity.INFO,
            {
                "csvRowNumber": row["_row_number"],
                "stopId": stop_id,
                # The generated entity returns the String default for an absent
                # stop_name, so the jar reports "" rather than dropping the key.
                # Measured on a station whose name is blank. Same shape as
                # attribution_without_role's attributionId.
                "stopName": row.get("stop_name") or "",
            },
        )
