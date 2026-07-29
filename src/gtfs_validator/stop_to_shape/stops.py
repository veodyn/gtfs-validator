"""`StopPoints`: a trip's stops as unit vectors, with the threshold each one is judged against.

The threshold is per stop rather than per feed, and it depends on two things at once: the route's
type, and whether the stop is the trip's first or last. A rail route's terminus gets four times the
distance allowance of everything else, because, as upstream puts it, agency shapes often do not
extend to the end of the track at a main station. That is a tolerance for a known data habit, not
a geometric argument, which is why it applies to rail alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from gtfs_validator.rules._shared.stop_coordinates import coordinates_of
from gtfs_validator.s2point import Point, to_point

# GtfsRouteType.RAIL, the only type that gets the large-station allowance.
RAIL_ROUTE_TYPE = 2


@dataclass(frozen=True)
class StopPoint:
    location: Point
    user_distance: float
    stop_time: dict
    is_large_station: bool

    def has_user_distance(self) -> bool:
        return self.user_distance > 0.0


class StopPoints:
    """One trip's stops, in `stop_sequence` order."""

    def __init__(self, points: list[StopPoint]) -> None:
        self.points = points

    @classmethod
    def from_stop_times(
        cls, stop_times: list[dict], stops: dict[str, dict], large_stations: bool
    ) -> StopPoints:
        """Build from one trip's `stop_times.txt` rows.

        A stop whose id resolves to nothing still becomes a point, at latitude 0 longitude 0, the
        way `StopUtil.getStopOrParentLatLng` falls back to `S2LatLng.CENTER`. Dropping it would
        renumber the sequence and change which stops count as first and last.
        """
        points: list[StopPoint] = []
        for stop_time in stop_times:
            # `points.isEmpty() || points.size() == stopTimes.size() - 1`, evaluated *before* the
            # append, so the second test names the last row rather than the one before it.
            first_or_last = not points or len(points) == len(stop_times) - 1
            distance = stop_time.get("shape_dist_traveled")
            points.append(
                StopPoint(
                    location=to_point(*coordinates_of(stops, stop_time.get("stop_id", ""))),
                    user_distance=0.0 if distance is None else distance,
                    stop_time=stop_time,
                    is_large_station=large_stations and first_or_last,
                )
            )
        return cls(points)

    def is_empty(self) -> bool:
        return not self.points

    def has_user_distance(self) -> bool:
        """The last stop's alone, as `Iterables.getLast` does, matching `ShapePoints`."""
        return bool(self.points) and self.points[-1].has_user_distance()


def large_stations_for_route_type(route_type: object) -> bool:
    """`StopPoints.routeTypeToStationSize`: rail is LARGE, everything else is SMALL.

    An unrecognised `route_type` compares unequal to the enum constant and so is SMALL, which is
    reachable: a route type outside the enum draws a warning rather than an error, so the row
    survives typing and reaches this.
    """
    return route_type == RAIL_ROUTE_TYPE
