"""ContinuousPickupDropOffValidator: continuous service and a booking window together.

A route offering continuous pickup or drop-off is served anywhere along its path, and a stop time
with a pickup or drop-off *window* is served during a period at a place. The two are different
service models and a feed cannot mean both at once.

Notices come out in upstream's traversal order: routes in file order, then that route's trips in
file order, then each trip's windowed stop times by stop_sequence. Nothing is de-duplicated, because
upstream iterates entities rather than an index: two trips sharing an id are two trips, and a
duplicated continuous route is reported once per row. A global sort by trip and a pair of dicts
halved the count on a duplicate probe and kept a different thousand above the sample cap.

Only the route's flags decide whether the check applies, and only three of the four values count as
continuous: allowed, must-phone and on-request-to-driver. Not-allowed and an absent value do not, so
a route leaving both columns blank is never reported.

One window is enough: the notice fires when *either* end is present, and reports both. The absent one
renders as "00:00:00", the GtfsTime default, which is the third of the three absent-value renderings
recorded here.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.render import hhmmss
from gtfs_validator.rules.registry import file_rule

CODE = "forbidden_continuous_pickup_drop_off"
ROUTES = "routes.txt"
TRIPS = "trips.txt"
STOP_TIMES = "stop_times.txt"
START_WINDOW = "start_pickup_drop_off_window"
END_WINDOW = "end_pickup_drop_off_window"

# GtfsContinuousPickupDropOff: ALLOWED, MUST_PHONE and ON_REQUEST_TO_DRIVER. NOT_ALLOWED is 1.
CONTINUOUS_VALUES = (0, 2, 3)
# GtfsTime's default, which is what an absent window renders as.
NO_TIME = "00:00:00"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # Windowed stop times grouped by trip, sorted by stop_sequence within a trip because that is the
    # order the container yields. Only rows carrying a window are kept, which is a small fraction of
    # any real feed.
    windows: dict[str, list[tuple[int, int, object, object]]] = {}
    for row in feed.rows_where_any_set(STOP_TIMES, (START_WINDOW, END_WINDOW), require="trip_id"):
        windows.setdefault(row["trip_id"], []).append(
            (
                row.get("stop_sequence") or 0,
                row["_row_number"],
                row.get(START_WINDOW),
                row.get(END_WINDOW),
            )
        )
    if not windows:
        return
    for entries in windows.values():
        entries.sort(key=lambda entry: entry[:2])

    # Trips grouped by route, in file order, and **not** de-duplicated: upstream iterates entities,
    # so two trips sharing an id are two trips and a duplicated continuous route is reported once per
    # row. Collapsing either into a dict halved the count on a duplicate probe.
    trips_by_route: dict[str, list[dict]] = {}
    for row in feed.rows(TRIPS):
        route_id = row.get("route_id")
        if route_id is not None:
            trips_by_route.setdefault(route_id, []).append(row)

    # Routes in file order, which is the outer loop upstream runs and therefore the order the
    # notices come out in. Sorting globally by trip instead kept a different thousand above the cap.
    for route in feed.rows(ROUTES):
        route_id = route.get("route_id")
        if route_id is None or not _is_continuous(route):
            continue
        for trip in trips_by_route.get(route_id, ()):
            for _, stop_time_row, start_window, end_window in windows.get(trip["trip_id"], ()):
                yield Notice(
                    CODE,
                    Severity.ERROR,
                    {
                        "routeCsvRowNumber": route["_row_number"],
                        "tripId": trip["trip_id"],
                        "stopTimeCsvRowNumber": stop_time_row,
                        "startPickupDropOffWindow": _time(start_window),
                        "endPickupDropOffWindow": _time(end_window),
                    },
                )


def _is_continuous(route: dict) -> bool:
    return (
        route.get("continuous_pickup") in CONTINUOUS_VALUES
        or route.get("continuous_drop_off") in CONTINUOUS_VALUES
    )


def _time(value: object) -> str:
    return NO_TIME if value is None else hhmmss(value)
