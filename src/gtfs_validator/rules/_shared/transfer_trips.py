"""The trip-reference walk both TransfersTripReferenceValidator codes share.

For each transfer, for each direction, the validator resolves the named trip and then asks two
independent questions: does the trip run on the route the transfer claims, and does it call at the
stop the transfer names. Neither is skipped because of the other.

Three skips leave the case to a rule that owns it: a direction with no trip id, a trip that does
not exist (the foreign key validators report that) and a stop that does not exist (likewise).

`expandStationIfNeeded` is the part worth reading twice. A platform stands for itself; a **station**
stands for its **direct children**, whatever their location type, so a transfer naming a station
is satisfied by a trip calling at any of them. A review checked the wording against a station whose
only child is itself a station: upstream does not filter by type and neither does this; and **anything else expands to the empty set**, so an entrance, a node or a boarding
area can never be served and always draws the notice. All three measured.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.rules._shared.in_seat import DIRECTIONS, Direction
from gtfs_validator.rules._shared.location_types import STATION, STOP, location_type_of

TRANSFERS = "transfers.txt"
TRIPS = "trips.txt"
STOPS = "stops.txt"
STOP_TIMES = "stop_times.txt"


def trip_references(feed) -> Iterator[tuple[dict, Direction, dict]]:
    """Each (transfer, direction, trip) whose trip resolves, in transfers.txt file order.

    Reading all four tables is the gate: the validator is injected with every one of them, so a
    failure in any silences both codes.
    """
    trips = _by_id(feed, TRIPS, "trip_id")
    for row in feed.rows(TRANSFERS):
        for direction in DIRECTIONS:
            trip_id = row.get(direction.trip_field)
            if trip_id is None:
                continue
            trip = trips.get(trip_id)
            if trip is None:
                continue
            yield row, direction, trip


def served_stop_ids(feed, trip_id: str) -> set[str]:
    """The stop ids a trip's stop times name.

    An indexed seek, because this runs once per transfer direction: as a full scan it
    was 5.6 seconds per call on a 1.64M-row stop_times, and a clean profile slice of a
    real feed showed a four-minute window containing 42 such scans and nothing else.
    """
    return {row.get("stop_id") for row in feed.rows_where(STOP_TIMES, "trip_id", trip_id)}


_STOPS_CACHE = "transfer_trips.stops"


def expanded_stop_ids(feed, stop_id: str) -> set[str] | None:
    """The ids a transfer's stop stands for, or None when the stop does not exist.

    A platform stands for itself, a station for its children, and any other location type for
    nothing at all, which is why this returns an empty set rather than None in that case: the
    difference is between "no notice" and "always a notice".
    """
    by_id, children = _stops_maps(feed)
    stop = by_id.get(stop_id)
    if stop is None:
        return None
    location_type = location_type_of(stop)
    if location_type == STOP:
        return {stop_id}
    if location_type == STATION:
        return set(children.get(stop_id, ()))
    return set()


def _stops_maps(feed) -> tuple[dict[str, dict], dict[str, set[str]]]:
    """stops by id (first row per id) and each station's direct children, built once.

    This ran as a fresh pass over stops.txt per transfer direction; the maps are what
    the two set comprehensions read, including a child row whose own stop_id is unset,
    which contributes None to its parent's set exactly as the scan did.
    """
    cached = feed.cache.get(_STOPS_CACHE)
    if cached is not None:
        return cached
    by_id: dict[str, dict] = {}
    children: dict[str, set[str]] = {}
    for row in feed.rows(STOPS):
        key = row.get("stop_id")
        if key is not None:
            by_id.setdefault(key, row)
        parent = row.get("parent_station")
        if parent is not None:
            children.setdefault(parent, set()).add(row.get("stop_id"))
    feed.cache[_STOPS_CACHE] = (by_id, children)
    return by_id, children


def _by_id(feed, filename: str, column: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for row in feed.rows(filename):
        key = row.get(column)
        if key is not None:
            rows.setdefault(key, row)
    return rows
