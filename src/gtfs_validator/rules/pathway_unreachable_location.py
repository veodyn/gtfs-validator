"""PathwayReachableLocationValidator: a location a station's pathways cannot connect both ways.

Once a station has pathways at all, every platform, boarding area and generic node in it must be
reachable from some entrance *and* able to reach some exit. The notice says which of the two failed,
so one pathway pointing the wrong way is distinguishable from no pathway at all.

Three exemptions, and each is the opposite of what a first implementation would do:

- A station with **no** pathways is exempt entirely, so a feed carrying one pathway does not report
  every platform it has.
- An **entrance or a station** is never reported, however unreachable. Exempt by location type
  rather than by reachability.
- A **platform that has boarding areas** is exempt, because such a platform need not have incident
  pathways of its own; its boarding areas are reported instead. Measured: a feed with two boarding
  areas under an unreachable platform draws two notices and not three.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import pathways, reachability
from gtfs_validator.rules._shared.location_types import (
    BOARDING_AREA,
    GENERIC_NODE,
    STOP,
    location_type_of,
)
from gtfs_validator.rules.registry import file_rule

CODE = "pathway_unreachable_location"
STOPS = "stops.txt"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    index = pathways.index_of(feed)
    stations = reachability.stations_with_pathways(index)
    if not stations:
        return
    entrances = reachability.entrance_ids(feed)
    from_entrances = reachability.reachable_from_entrances(index, entrances)
    to_exits = reachability.reaching_exits(index, entrances)

    # `stopTable.getEntities()`, so file order rather than any index's. Read again rather than
    # walked from the index, which keeps a duplicated stop id reported once per row as upstream's
    # entity list holds it.
    for row in feed.rows(STOPS):
        stop_id = row.get("stop_id")
        if stop_id is None:
            continue
        station = reachability.including_station(index.stops, stop_id)
        if station is None or station["stop_id"] not in stations:
            continue
        if not _is_reportable(index, row, stop_id):
            continue
        has_entrance = stop_id in from_entrances
        has_exit = stop_id in to_exits
        if has_entrance and has_exit:
            continue
        yield Notice(
            CODE,
            Severity.ERROR,
            {
                "csvRowNumber": row["_row_number"],
                "stopId": stop_id,
                "stopName": row.get("stop_name") or "",
                # `locationTypeValue()`, the raw number rather than the enum's name, so a type
                # outside the enum reports its own value.
                "locationType": location_type_of(row),
                "parentStation": row.get("parent_station") or "",
                "hasEntrance": has_entrance,
                "hasExit": has_exit,
            },
        )


def _is_reportable(index: pathways.PathwayIndex, row: dict, stop_id: str) -> bool:
    """Whether this location's type puts it in scope at all.

    Generic nodes and boarding areas always are. A platform is only when it has no boarding areas of
    its own, which is the exemption that moves the notice down a level.
    """
    location_type = location_type_of(row)
    if location_type in (GENERIC_NODE, BOARDING_AREA):
        return True
    return location_type == STOP and not index.children.get(stop_id)
