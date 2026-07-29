"""How `_shared/travel_speed` groups trips, and the order the groups come out in.

Its own module because the grouping belongs to neither rule: one upstream validator groups the
feed's trips once and runs both scans over each group, so the order is shared behaviour and the
two rule modules test what they do with a group rather than how one is made.

The order matters for the same reason every bucket order in this project matters. Above the
1,000-sample cap it decides which notices a report keeps, and this one is two bucket orders
composed: trips into groups by trip id, then groups into output by fingerprint.
"""

from __future__ import annotations

from fasttravel import T0800, feed, stop, stop_time, trip
from gtfs_validator.rules._shared import travel_speed

# Ten trips. TK1 and TK2 call at the same stop and so share a group; every other trip calls at
# its own and is a group of one. Nine groups from ten trips, which is the shape that makes both
# orderings observable at once.
TRIP_IDS = ["T0", "T1", "T2", "T3", "T4", "T5", "T6", "TK1", "TK2", "TL"]


def stop_id_for(trip_id: str) -> str:
    return "STK" if trip_id.startswith("TK") else f"S{trip_id}"


def grouping():
    """`analysis` over a feed of one stop time per trip, as a list of member-id lists."""
    rows = [
        stop_time(number, trip_id, 1, stop_id_for(trip_id), T0800)
        for number, trip_id in enumerate(TRIP_IDS, 2)
    ]
    stop_ids = sorted({stop_id_for(trip_id) for trip_id in TRIP_IDS})
    view = feed(
        rows,
        trips=[trip(trip_id, number) for number, trip_id in enumerate(TRIP_IDS, 2)],
        stop_rows=[stop(stop_id, 2 + index, 40.0) for index, stop_id in enumerate(stop_ids)],
    )
    _, groups = travel_speed.analysis(view)
    return [[member["trip_id"] for member in group.trips] for group in groups]


def test_groups_come_out_in_the_order_the_multimap_was_populated():
    """A group takes the position of its *earliest* member in the trip-id multimap's order.

    Upstream builds the fingerprint multimap while walking the trip-id map, so a group is
    inserted when its first member is reached, and `long_multimap_order` needs its keys in that
    order because within a bucket the order is insertion.

    This is pinned because the rows no longer arrive in that order. `stop_times.txt` is
    streamed one trip at a time in whatever order the store finds cheapest, so the fingerprints
    are collected in the wrong order and have to be put back. Handing them over as collected
    puts T0 first here instead of T6, and moves nothing else. Ten trips is the smallest feed of
    this shape where the two disagree at all, which is why the streaming rewrite matched the jar
    on all three travel-speed probes and 297 of 298 probe feeds before this was noticed.
    """
    assert grouping() == [
        ["T6"],
        ["T0"],
        ["TL"],
        ["T5"],
        ["TK2", "TK1"],
        ["T3"],
        ["T1"],
        ["T4"],
        ["T2"],
    ]


def test_members_of_a_group_come_out_in_the_multimap_order_too():
    """TK2 before TK1, which is neither the file order nor the sorted one.

    The same question one level down from the group order, and a separate assertion because a
    single wrong sort key can get one right and the other wrong: the members are ordered by
    where the trip id falls, the groups by where the group's first trip does.
    """
    assert [group for group in grouping() if len(group) > 1] == [["TK2", "TK1"]]
