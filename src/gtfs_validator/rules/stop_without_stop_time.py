"""LocationHasStopTimesValidator: a platform no trip calls at.

Only a stop of location_type STOP is expected to have stop times, so this is the half of the
validator that fires on absence; `location_with_unexpected_stop_time` is the half that fires
on presence, and the two are opposites rather than variations.

A stop can be served without being named: a stop time naming a location group serves every
stop in that group, and those are exempt. Dropping the exemption reports a stop the jar
accepts, measured.

LocationHasStopTimesValidator takes three containers and upstream skips it if any of them
failed, including location_group_stops.txt: measured on a group file whose second row leaves
the required stop_id blank, where the jar reports neither of this validator's notices. An
*absent* location_group_stops.txt is different, and does not stop it.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import STOP, location_type_of
from gtfs_validator.rules._shared.stop_time_usage import (
    stops_reached_through_location_groups,
    usage_of,
)
from gtfs_validator.rules.registry import file_rule

CODE = "stop_without_stop_time"

# Upstream injects these containers, and a failure in any of them skips the validator.
DEPENDENCIES = ("stops.txt", "stop_times.txt", "location_group_stops.txt")


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if any(feed.dependency_failed(name) for name in DEPENDENCIES):
        return
    served = set(usage_of(feed).first_row_by_stop)
    served |= stops_reached_through_location_groups(feed)
    for row in feed.rows("stops.txt"):
        stop_id = row.get("stop_id")
        if stop_id is None or location_type_of(row) != STOP or stop_id in served:
            continue
        yield Notice(
            CODE,
            Severity.WARNING,
            {
                "csvRowNumber": row["_row_number"],
                "stopId": stop_id,
                "stopName": row.get("stop_name") or "",
            },
        )
