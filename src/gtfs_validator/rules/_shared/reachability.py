"""The pathway graph traversal behind `pathway_unreachable_location`.

Two breadth-first searches over `pathways.txt`, both seeded with **every entrance in the feed**: one
following pathways in their own direction, one against it. A location is well connected when it
appears in both visited sets, meaning some entrance can reach it and it can reach some exit.

The seeding is feed-wide rather than per station, which is measurable and is the opposite of the
natural design. On a feed whose only entrance is in station 1 and whose bidirectional pathway runs
from it to a platform in station 2, the jar reports station 1's own platform and stays silent about
station 2's. A per-station traversal reports exactly the other one.

Split from the rule module because the traversal and the station walk are the parts worth reading
separately from the reporting rules, and because a second reachability code would share them.
"""

from __future__ import annotations

from collections import deque

from gtfs_validator.rules._shared.location_types import ENTRANCE, STATION, location_type_of
from gtfs_validator.rules._shared.pathways import FROM_STOP_ID, TO_STOP_ID, PathwayIndex

# GtfsPathwayIsBidirectional.BIDIRECTIONAL. The field is required, and an unset one reads as 0,
# which is UNIDIRECTIONAL: a pathway missing the column is one-way rather than two-way.
BIDIRECTIONAL = 1
STOPS = "stops.txt"
# `for (int i = 0; i < 3; ++i)` in StopUtil.getIncludingStation, which bounds the walk against a
# parent cycle. Three is also the depth GTFS allows: station, platform, boarding area.
MAX_HOPS = 3


def including_station(stops: dict[str, dict], stop_id: str) -> dict | None:
    """`StopUtil.getIncludingStation`: the station this location belongs to, or None.

    A location that *is* a station returns itself. The walk stops at the first station found rather
    than at the top of the chain, and gives up after three lookups whether or not it found one,
    because a feed can contain a cycle of parents and this is called from a validator that has to
    terminate.
    """
    for _ in range(MAX_HOPS):
        stop = stops.get(stop_id)
        if stop is None:
            return None
        if location_type_of(stop) == STATION:
            return stop
        parent = stop.get("parent_station")
        # `if (!location.hasParentStation()) break`, a presence test: a parent_station that is
        # present and empty is a hop to the station whose id is "", not the end of the walk.
        if parent is None:
            return None
        stop_id = parent
    return None


def stations_with_pathways(index: PathwayIndex) -> set[str]:
    """The ids of stations holding at least one location that a pathway touches.

    Every other station is exempt from the whole rule, which is what keeps a feed carrying one
    pathway from reporting every platform it has.
    """
    found: set[str] = set()
    for stop_id in set(index.by_from) | set(index.by_to):
        station = including_station(index.stops, stop_id)
        if station is not None:
            found.add(station["stop_id"])
    return found


def entrance_ids(feed) -> list[str]:
    """Every entrance in `stops.txt`, in file order, read from the rows rather than from an index.

    `stopTable.getEntities()` holds **every** row, including both sides of a duplicated `stop_id`,
    where an index keyed by id keeps only the first. That difference is observable: on a feed whose
    id `X` appears first as a platform and then as an entrance, upstream seeds the traversal from
    the entrance row and reports nothing, while seeding from a first-wins index sees a platform,
    seeds nothing, and reports both `X` and the platform behind it. Measured on `reach/pr14`.
    """
    return [
        row["stop_id"]
        for row in feed.rows(STOPS)
        if row.get("stop_id") is not None and location_type_of(row) == ENTRANCE
    ]


def reachable_from_entrances(index: PathwayIndex, entrances: list[str]) -> set[str]:
    """Locations some entrance can reach, following pathways in their own direction."""
    return _traverse(index, entrances, from_entrances=True)


def reaching_exits(index: PathwayIndex, entrances: list[str]) -> set[str]:
    """Locations that can reach some entrance, following pathways against their direction."""
    return _traverse(index, entrances, from_entrances=False)


def _traverse(index: PathwayIndex, entrances: list[str], *, from_entrances: bool) -> set[str]:
    """One breadth-first search, returning every visited id including the entrances themselves.

    A bidirectional pathway is traversable whichever way the search runs, which is the whole of
    upstream's handling of them: there is no separate case.

    The queue holds ids rather than rows, and an id that no `stops.txt` row defines is still
    enqueued. `toStopId()` on a pathway is a string and whether it names a real location is another
    rule's notice, so upstream bridges *through* a missing stop: a feed with `EN -> MISSING` and
    `MISSING -> P` leaves P reachable. Dropping unknown ids here would disconnect it instead.
    """
    visited: set[str] = set()
    queue: deque[str] = deque(entrances)
    visited.update(entrances)
    while queue:
        current = queue.popleft()
        for pathway in index.by_from.get(current, ()):
            if from_entrances or pathway.get("is_bidirectional") == BIDIRECTIONAL:
                _visit(pathway.get(TO_STOP_ID) or "", visited, queue)
        for pathway in index.by_to.get(current, ()):
            if not from_entrances or pathway.get("is_bidirectional") == BIDIRECTIONAL:
                _visit(pathway.get(FROM_STOP_ID) or "", visited, queue)
    return visited


def _visit(stop_id: str, visited: set[str], queue: deque[str]) -> None:
    if stop_id not in visited:
        visited.add(stop_id)
        queue.append(stop_id)
