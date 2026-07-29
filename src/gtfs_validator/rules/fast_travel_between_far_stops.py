"""StopTimeTravelSpeedValidator's span scan: too fast between two stops more than 10 km apart.

The other half of the validator behind `fast_travel_between_consecutive_stops`, and not a
threshold away from it. For every stop time with an arrival, upstream walks *backwards*
accumulating the hop distances, and reports the first pair that is both over the route's speed
threshold and over 10 km apart. Then it stops looking at the trip.

That reaches feeds the neighbour scan cannot. A trip of eleven stops 1.22 km apart, all timed
at the same minute, has no fast hop at all: equal times clamp to a minute, which is 73 km/h
against a bus's 150. Its span is 11 km in that same minute, and the jar reports it at 660.5
km/h. The distances come from the array built for the group, so a hop whose stop resolved
nowhere contributes 0 to the sum rather than breaking it.

Two ways out of the scan, and they differ from the neighbour scan's:

- A stop time whose **stop id resolves to no row** ends the trip's analysis, rather than
  skipping its own pair. Measured on a trip whose middle row names an undeclared stop: the
  neighbour scan reports the pair either side of it and this one reports nothing at all.
- The first reported pair ends it too, so a trip draws at most one notice per group member.

The notice names each trip's own stop time rows, unlike the neighbour scan, which names the
group's first trip's for every notice. Two identical probe trips are what settles that: their
far-stop notices carry different row numbers and their consecutive ones carry the same.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import travel_speed
from gtfs_validator.rules.registry import file_rule

CODE = "fast_travel_between_far_stops"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    stops, groups = travel_speed.analysis(feed)
    for group in groups:
        yield from _scan(feed, stops, group)


def _scan(feed, stops, group) -> Iterator[Notice]:
    """One group's backward walk. A function of its own so that upstream's two `return`s,
    which leave the whole trip rather than one iteration, stay `return`s here."""
    rows, distances_km = travel_speed.scan_rows(feed, stops, group)
    for end_index, end in enumerate(rows):
        if end.get(travel_speed.ARRIVAL) is None:
            continue
        end_stop = stops.get(end.get(travel_speed.STOP_ID) or "")
        if end_stop is None:
            # A broken reference is reported in another rule, and upstream gives up on the
            # trip here rather than moving to the next stop time.
            return
        distance = 0.0
        for start_index in range(end_index - 1, -1, -1):
            start = rows[start_index]
            distance += distances_km[start_index]
            if start.get(travel_speed.DEPARTURE) is None:
                continue
            speed = travel_speed.speed_kph(distance, start, end)
            if speed <= group.max_speed_kph:
                continue
            start_stop = stops.get(start.get(travel_speed.STOP_ID) or "")
            if start_stop is None:
                return
            if distance > travel_speed.FAR_THRESHOLD_KM:
                yield from _notices(
                    feed, group, start_index, start_stop, end_index, end_stop, speed, distance
                )
                return


def _notices(
    feed, group, start_index, start_stop, end_index, end_stop, speed, distance
) -> Iterator[Notice]:
    """One notice per trip, each naming its own rows at the two positions found.

    Each member's rows are fetched here and dropped again, rather than carried on the group:
    only a group that reports needs them, and only two of them are read. Every member has the
    same number of rows, since the fingerprint covers the stop-time count and each stop's id
    and times, which is the same reason upstream can index them by the position it found.
    """
    for trip in group.trips:
        rows = travel_speed.rows_for_trip(feed, trip)
        yield Notice(
            CODE,
            Severity.WARNING,
            travel_speed.pair_context(
                trip,
                rows[start_index],
                start_stop,
                rows[end_index],
                end_stop,
                speed,
                distance,
            ),
        )
