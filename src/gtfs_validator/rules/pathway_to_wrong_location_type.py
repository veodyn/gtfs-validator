"""PathwayEndpointTypeValidator: a pathway may not end at a station.

Both endpoints are checked, so one pathway can draw two notices, and `fieldName` names
which end was wrong. A station is the parent of the platforms and entrances a pathway
should connect, never a node in the graph itself.

An endpoint naming a stop that does not exist is skipped: upstream returns early when the
lookup is empty, leaving the broken reference to foreign_key_violation.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import STATION, location_type_of
from gtfs_validator.rules._shared.pathways import FROM_STOP_ID, TO_STOP_ID, index_of
from gtfs_validator.rules.registry import file_rule

CODE = "pathway_to_wrong_location_type"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    index = index_of(feed)
    for row in index.pathways:
        for field in (FROM_STOP_ID, TO_STOP_ID):
            stop_id = row.get(field)
            stop = index.stops.get(stop_id) if stop_id is not None else None
            if stop is None or location_type_of(stop) != STATION:
                continue
            yield Notice(
                CODE,
                Severity.ERROR,
                {
                    "csvRowNumber": row["_row_number"],
                    "pathwayId": row.get("pathway_id") or "",
                    "fieldName": field,
                    "stopId": stop_id,
                },
            )
