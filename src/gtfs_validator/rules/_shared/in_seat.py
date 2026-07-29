"""What the two TransfersInSeatTransferTypeValidator checks share.

An in-seat transfer names trips rather than only stops. Type 4 says the passenger stays in the
vehicle; type 5 says they may not, and upstream validates both identically, because either way the
row is a statement about a specific pair of trips meeting at a specific stop. Both of its checks need the same three things: the
transfer's per-direction fields, the stop it names, and the trip's first and last stop.

"""

from __future__ import annotations

from dataclasses import dataclass

FILENAME = "transfers.txt"
STOPS = "stops.txt"
STOP_TIMES = "stop_times.txt"

# GtfsTransferType.IN_SEAT_TRANSFER_ALLOWED and IN_SEAT_TRANSFER_NOT_ALLOWED.
IN_SEAT_TYPES = (4, 5)
_CACHE_KEY = "in_seat.trip_ends"


@dataclass(frozen=True)
class Direction:
    """One end of a transfer, and the field names its notices report."""

    stop_field: str
    trip_field: str
    #: Whether the transfer stop should be the trip's last stop rather than its first.
    wants_last: bool
    #: Upstream's TransferDirection carries the route field too, which the trip-reference
    #: codes report. It lives here rather than in a second record because it is one concept.
    route_field: str


DIRECTIONS = (
    Direction("from_stop_id", "from_trip_id", wants_last=True, route_field="from_route_id"),
    Direction("to_stop_id", "to_trip_id", wants_last=False, route_field="to_route_id"),
)


def in_seat_transfers(feed) -> list[dict]:
    return [row for row in feed.rows(FILENAME) if row.get("transfer_type") in IN_SEAT_TYPES]


def trip_ends(feed) -> dict[str, tuple[str | None, str | None, set[str]]]:
    """Per trip: its first stop, its last stop, and every stop it calls at.

    Ordered by stop_sequence, because that is the order the container yields and the whole question
    is which stop comes first and last. The set is what decides whether the check applies at all:
    upstream skips a transfer whose stop the trip never visits, leaving it to the trip-reference
    validator.

    Three values per trip rather than the trip's stop times, which is smaller but **not** bounded by
    trips: the stop set grows with the number of distinct trip-stop pairs, and `in_seat_transfers`
    materialises every in-seat transfer besides. Saying "bounded by trips" was wrong. A feed with
    long trips holds one entry per stop visited, so this is the aggregate to revisit first if the
    scale harness ever moves.
    """
    cached = feed.cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    best: dict[str, tuple[tuple[int, int], tuple[int, int], str, str, set[str]]] = {}
    for row in feed.rows(STOP_TIMES):
        trip_id, stop_id = row.get("trip_id"), row.get("stop_id")
        if trip_id is None or stop_id is None:
            continue
        key = (row.get("stop_sequence") or 0, row["_row_number"])
        entry = best.get(trip_id)
        if entry is None:
            best[trip_id] = (key, key, stop_id, stop_id, {stop_id})
            continue
        low, high, first, last, visited = entry
        visited.add(stop_id)
        if key < low:
            low, first = key, stop_id
        if key > high:
            high, last = key, stop_id
        best[trip_id] = (low, high, first, last, visited)
    ends = {
        trip_id: (first, last, visited) for trip_id, (_, _, first, last, visited) in best.items()
    }
    feed.cache[_CACHE_KEY] = ends
    return ends
