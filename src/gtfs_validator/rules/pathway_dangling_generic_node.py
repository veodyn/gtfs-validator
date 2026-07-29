"""PathwayDanglingGenericNodeValidator: a generic node that leads nowhere.

A generic node exists to join two parts of a path, so it needs at least two distinct
neighbours. Upstream counts the *set* of far endpoints and reports when the size is
exactly one, which has a consequence worth stating: a node with **no** pathways at all is
not reported here, and neither is one with two. Measured on a feed carrying all three
shapes.

Two pathways to the same neighbour still count as one, since the set collapses them.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import GENERIC_NODE, location_type_of
from gtfs_validator.rules._shared.pathways import FROM_STOP_ID, TO_STOP_ID, index_of
from gtfs_validator.rules.registry import file_rule

CODE = "pathway_dangling_generic_node"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    index = index_of(feed)
    for stop_id, stop in index.stops.items():
        if location_type_of(stop) != GENERIC_NODE:
            continue
        neighbours = {row.get(TO_STOP_ID) for row in index.by_from.get(stop_id, ())}
        neighbours |= {row.get(FROM_STOP_ID) for row in index.by_to.get(stop_id, ())}
        if len(neighbours) != 1:
            continue
        yield Notice(
            CODE,
            Severity.WARNING,
            {
                "csvRowNumber": stop["_row_number"],
                "stopId": stop_id,
                "stopName": stop.get("stop_name") or "",
                "parentStation": stop.get("parent_station") or "",
            },
        )
