"""BlockTripsWithOverlappingStopTimesValidator: two trips in a block scheduled against each other.

A block is a vehicle. Two trips sharing one that run at the same time on the same day describe a
vehicle in two places at once, so the check is per block: build each trip's interval from its
first and last stop time, sort, and compare each trip with the later ones.

Three things decide whether a pair is reported, and they are easy to collapse into one:

- **The break.** Once a later trip starts at or after this one ends, no trip after it can
  overlap either, so the whole inner loop ends. The comparison is `<=`, so two trips that meet
  exactly do not overlap. Measured on a probe whose trips touch at 09:00 and draw nothing.
- **The skip.** A pair whose handover is exact, meaning this trip's last arrival *and* last
  departure equal the next trip's first arrival and first departure, is passed over and the
  search continues. Agencies model a block transfer by repeating the stop time on both trips,
  which is a real overlap that upstream chooses to allow. Both fields have to match: moving the
  departure by a minute makes it a notice.
- **The service intersection.** The pair is only reported if some date runs both services, and
  the date reported is the first such. See `_shared/service_intersection`.

A trip contributes an interval only if it has stop times *and* all four of its first and last
arrival and departure are set. An absent time is not defaulted to midnight here, which is the
one place in this validator where the type default does not apply: `hasArrivalTime()` is asked
directly. A probe whose first stop time has an arrival and no departure draws nothing, where
defaulting would have made the trip span midnight to 09:00 and overlap its neighbour.

The intervals sort by first arrival, then last departure, and the sort decides which trip of a
pair is the notice's `A`. Measured on a block written later-trip-first, where the jar names the
second row before the first.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from gtfs_validator.context import Context
from gtfs_validator.javahash import multimap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import calendars, stop_time_trips
from gtfs_validator.rules._shared.service_intersection import ServiceIntersections
from gtfs_validator.rules.registry import file_rule

CODE = "block_trips_with_overlapping_stop_times"
TRIPS = "trips.txt"
BLOCK_ID = "block_id"
ARRIVAL = "arrival_time"
DEPARTURE = "departure_time"


@dataclass(frozen=True)
class _Interval:
    """A trip's span, as the first and last stop time's four times."""

    trip: dict
    first_arrival: int
    first_departure: int
    last_arrival: int
    last_departure: int

    @property
    def sort_key(self) -> tuple[int, int]:
        return (self.first_arrival, self.last_departure)


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # `if (tripTable.entityCount() == 0 || stopTimeTable.entityCount() == 0) return;` Both halves,
    # not just the trips: without the second, a feed with trips and no stop times still builds
    # every service period for the intersection cache before finding there is nothing to compare.
    trips_by_block = _by_block(feed)
    if not trips_by_block or not stop_time_trips.trip_ids(feed):
        return
    # Built once for the feed rather than per block: a service pair repeats across blocks, and
    # the whole point of the cache is that the second question is free.
    intersections = ServiceIntersections(feed)
    for block_id in multimap_order(trips_by_block):
        members = trips_by_block[block_id]
        # `!tripsInBlock.get(0).hasBlockId()`. The container keys a trip with no block id under
        # the type default, so the group exists and has to be recognised by its contents.
        #
        # `is None`, not truthiness. `hasBlockId()` asks whether the column carried a value, and a
        # cell of `" "` is trimmed to `""` while staying present, so upstream compares those trips.
        # Truthiness skipped them: measured on the `ws3` probe, where the jar reports an
        # overlapping pair with `blockId: ""` and we reported nothing. Grouping still uses `or ""`
        # above, because upstream's multimap keys absent and empty alike under the type default;
        # it is only this presence test that has to tell them apart.
        if members[0].get(BLOCK_ID) is None:
            continue
        yield from _overlaps(feed, members, intersections)


def _by_block(feed) -> dict[str, list[dict]]:
    """trips.txt grouped by block id, keyed in file order of first appearance.

    Whole rows, and all of them: the notice names three fields of each trip, and trips.txt is
    already held whole by several rules. `stop_times.txt` is the table that may not be, which is
    why the stop times below are read a trip at a time.
    """
    grouped: dict[str, list[dict]] = {}
    for row in feed.rows(TRIPS):
        grouped.setdefault(row.get(BLOCK_ID) or "", []).append(row)
    return grouped


def _overlaps(feed, members: list[dict], intersections: ServiceIntersections) -> Iterator[Notice]:
    intervals = sorted(_intervals(feed, members), key=lambda interval: interval.sort_key)
    for index, interval in enumerate(intervals):
        for following in intervals[index + 1 :]:
            if interval.last_departure <= following.first_arrival:
                # Nothing later can overlap either, since the list is sorted by first arrival.
                break
            if (
                interval.last_arrival == following.first_arrival
                and interval.last_departure == following.first_departure
            ):
                # An exact handover, which upstream allows. The search continues past it.
                continue
            shared = intersections.first_shared_date(
                interval.trip.get("service_id") or "", following.trip.get("service_id") or ""
            )
            if shared is None:
                continue
            yield Notice(CODE, Severity.ERROR, _context(interval.trip, following.trip, shared))


def _intervals(feed, members: list[dict]) -> Iterator[_Interval]:
    """One interval per trip that has stop times and all four edge times.

    The trips are visited in the group's own order, which is file order, and the sort afterwards
    is stable, so two trips with identical spans stay in file order.
    """
    for trip in members:
        rows = stop_time_trips.rows_for_trip(feed, trip["trip_id"])
        if not rows:
            # A trip with no stop times is another rule's notice.
            continue
        first, last = rows[0], rows[-1]
        times = (
            first.get(ARRIVAL),
            first.get(DEPARTURE),
            last.get(ARRIVAL),
            last.get(DEPARTURE),
        )
        if any(time is None for time in times):
            continue
        yield _Interval(trip, *times)


def _context(first: dict, second: dict, shared) -> dict:
    """The notice's eight fields in Gson's order. `blockId` is the first trip's."""
    return {
        "csvRowNumberA": first["_row_number"],
        "tripIdA": first.get("trip_id") or "",
        "serviceIdA": first.get("service_id") or "",
        "csvRowNumberB": second["_row_number"],
        "tripIdB": second.get("trip_id") or "",
        "serviceIdB": second.get("service_id") or "",
        "blockId": first.get(BLOCK_ID) or "",
        "intersection": calendars.render_gtfs_date(shared),
    }
