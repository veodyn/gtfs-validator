"""MissingLevelIdValidator: an elevator endpoint that does not say which floor.

Only endpoints of a pathway whose mode is ELEVATOR, and only those whose stop
carries no level_id. Measured: an elevator between a platform with a level and one
without reports the one without, while a walkway endpoint with no level is untouched.

A named endpoint that is not in stops.txt is skipped; the broken reference is another
rule's to report.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule

# GtfsPathwayMode.ELEVATOR.
ELEVATOR = 5


@file_rule(code="missing_level_id", severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    endpoints: set[str] = set()
    for pathway in feed.rows("pathways.txt"):
        if pathway.get("pathway_mode") != ELEVATOR:
            continue
        for end in ("from_stop_id", "to_stop_id"):
            stop_id = pathway.get(end)
            if stop_id is not None:
                endpoints.add(stop_id)
    if not endpoints:
        return
    # Walked in stops.txt order rather than the set's, so the output is deterministic
    # where upstream's HashSet iteration is not. The harness compares samples as a
    # sorted multiset, so order is not part of the contract either way.
    for stop in feed.rows("stops.txt"):
        stop_id = stop.get("stop_id")
        if stop_id not in endpoints or stop.get("level_id") is not None:
            continue
        yield Notice(
            "missing_level_id",
            Severity.ERROR,
            {
                "csvRowNumber": stop["_row_number"],
                "stopId": stop_id,
                # The generated entity returns the String default, so a blank name
                # reports "" rather than dropping the key; see unused_station.
                "stopName": stop.get("stop_name") or "",
            },
        )
