"""StopTimeTravelSpeedValidator's neighbour scan: too fast between two stops in a row.

A walk down each group's first trip comparing a stop's departure with the next stop's
arrival. The threshold comes from the route type, so a train may outrun a bus, and the
elapsed time gets two adjustments that both change the reported speed: see
`_shared/travel_speed.time_between`.

The cursor is the part a plain reading gets wrong. Upstream keeps a `start` variable and
advances it *only* at the bottom of the loop body, so both of the `continue`s above it leave
it where it was. A stop whose distance cannot be measured, and a stop with no arrival time,
are therefore not merely skipped: the next comparison reaches back across them. Measured on
two probe trips whose notices name rows two apart with the distance of the longer span.

The notice names the group's first trip's stop times whatever trip it is about, which is
upstream's and not a simplification here: two identical probe trips both report the second
one's row numbers. `fast_travel_between_far_stops`, from the same validator, uses each trip's
own rows for the same fields.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import travel_speed
from gtfs_validator.rules.registry import file_rule

CODE = "fast_travel_between_consecutive_stops"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    stops, groups = travel_speed.analysis(feed)
    for group in groups:
        rows, _ = travel_speed.scan_rows(feed, stops, group)
        start = rows[0]
        for index in range(len(rows) - 1):
            end = rows[index + 1]
            first = travel_speed.coordinates(stops, start)
            second = travel_speed.coordinates(stops, end)
            if first is None or second is None:
                # One of the stops has no coordinates, which a GeoJSON location never does.
                continue
            if start.get(travel_speed.DEPARTURE) is None or end.get(travel_speed.ARRIVAL) is None:
                continue
            distance = travel_speed.distance_km(first, second)
            speed = travel_speed.speed_kph(distance, start, end)
            if speed > group.max_speed_kph:
                yield from _notices(stops, group, start, end, speed, distance)
            start = end


def _notices(stops, group, start, end, speed, distance) -> Iterator[Notice]:
    """One notice per trip in the group, all naming the same two stop time rows."""
    # Upstream calls this a precaution: the distance above was measured, which needed both
    # stops to resolve, and resolving starts at the stop's own row. Kept so that a feed which
    # somehow reaches it stays silent here rather than raising.
    start_stop = stops.get(start.get(travel_speed.STOP_ID) or "")
    end_stop = stops.get(end.get(travel_speed.STOP_ID) or "")
    if start_stop is None or end_stop is None:
        return
    for trip in group.trips:
        yield Notice(
            CODE,
            Severity.WARNING,
            travel_speed.pair_context(trip, start, start_stop, end, end_stop, speed, distance),
        )
