"""The trip fingerprint `StopTimeTravelSpeedValidator` groups by.

Upstream does not scan every trip. It first collapses trips that would produce identical
findings, keyed by a 64-bit fingerprint of the route id and the stop pattern: stop ids with
arrival and departure times. One trip of each group is analysed and every trip in the group
gets the notices. Two trips of the same route calling at the same stops at the same times are
therefore one unit of work, which is what keeps a feed of a thousand identical weekday trips
from being a thousand scans.

Grouping by the tuple would collapse the same trips. The fingerprint is here because its
*value* is also the multimap key, so it decides the order the groups, and therefore the
notices, come out in. See `gtfs_validator.farmhash`.

Two details of the byte stream are Java's rather than Python's, and both change the hash:

- `String.length()` counts UTF-16 code units, so an id holding an emoji is longer than its
  character count. Measured against Guava: using the character count disagreed on every trip
  whose route or stop id held a non-BMP character.
- An unset time is not skipped. `GtfsTime.getSecondsSinceMidnight()` on the type default is
  0, and the fingerprint takes it, so a stop time with no times still contributes eight bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from gtfs_validator.farmhash import Hasher
from gtfs_validator.javahash import long_multimap_order, multimap_order
from gtfs_validator.javatext import utf16_length
from gtfs_validator.rules._shared import stop_coordinates, stop_time_trips
from gtfs_validator.rules._shared.render import hhmmss
from gtfs_validator.s2earth import distance_meters

ARRIVAL = "arrival_time"
DEPARTURE = "departure_time"
STOP_ID = "stop_id"
SEQUENCE = "stop_sequence"
TRIPS = "trips.txt"
ROUTES = "routes.txt"

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
# MAX_DISTANCE_OVER_MAX_SPEED_IN_KMS: under this, a speeding pair is the consecutive code's
# business and this one stays quiet.
FAR_THRESHOLD_KM = 10.0
# getMaxVehicleSpeedKph, keyed by the enum's numbers. The comments are upstream's reasons.
MAX_SPEED_KPH = {
    0: 100.0,  # light rail: the Houston METRORail reaches 100
    1: 150.0,  # subway
    2: 500.0,  # rail: a maglev bullet train reaches 500
    3: 150.0,  # bus
    4: 80.0,  # ferry
    5: 30.0,  # cable tram: a cable car averages 15, with a safety gap
    6: 50.0,  # aerial lift: a fast aerial tramway runs at 43, with a safety gap
    7: 50.0,  # funicular
    11: 150.0,  # trolleybus
    12: 150.0,  # monorail
}
# The `default:` arm. Reachable: a route_type outside the enum draws a warning rather than an
# error, so the row is kept and its getter returns the unrecognised constant. Measured on a
# route of type 99, whose trip is reported at 222.39 km/h.
DEFAULT_MAX_SPEED_KPH = 200.0

_CACHE_KEY = "travel_speed_groups"


@dataclass(frozen=True)
class Group:
    """Trips upstream considers interchangeable, and the threshold their route sets.

    `trips` holds the trips.txt rows in the order the trip-id multimap yields them, and the
    first of them is the one upstream analyses. Which rows a notice *names* differs between the
    two codes and is each rule's business, not this one's.

    **No stop times here, and no hop distances either.** Both are per trip, and a feed where
    every trip has its own stop pattern is a feed with one group per trip, so keeping either
    would hold the whole of `stop_times.txt` by a longer route. `scan_rows` fetches the first
    trip's rows and measures its hops when a rule is ready to walk them.
    """

    trips: list[dict]
    max_speed_kph: float


def analysis(feed) -> tuple[dict[str, dict], list[Group]]:
    """The stops index and the groups, built once per feed for both rules.

    Both codes come from one upstream validator that groups the feed's trips once and runs
    both scans over each group. Two rules doing that separately would fingerprint every trip
    twice, so the result is memoised the way the other shared helpers do it.
    """
    cached = feed.cache.get(_CACHE_KEY)
    if cached is None:
        cached = _build(feed)
        feed.cache[_CACHE_KEY] = cached
    return cached


def _build(feed) -> tuple[dict[str, dict], list[Group]]:
    stops = stop_coordinates.stops_by_id(feed)
    trips = _first_by_id(feed, TRIPS, "trip_id")
    routes = _first_by_id(feed, ROUTES, "route_id")

    # The rank a trip has in the multimap's key order, which is the order its group's members
    # must end up in. Taken first so the rows below can arrive in any order at all: computing
    # the fingerprints needs every trip's stop times, and streaming them in the store's own
    # order costs one table scan where seeking each trip in rank order costs a seek apiece.
    rank = {
        trip_id: index
        for index, trip_id in enumerate(multimap_order(stop_time_trips.trip_ids(feed)))
    }
    grouped: dict[int, list[dict]] = {}
    for trip_id, rows in stop_time_trips.stream_trips(feed):
        trip = trips.get(trip_id)
        if trip is None:
            # `tripTable.byTripId(...).map(...).ifPresent(...)`: a stop time whose trip is not
            # declared never joins a group. The broken reference is another rule's to report.
            continue
        fingerprint = trip_fingerprint(trip.get("route_id") or "", rows)
        grouped.setdefault(fingerprint, []).append(trip)

    for members in grouped.values():
        members.sort(key=lambda trip: rank[trip["trip_id"]])
    # `long_multimap_order` needs its keys in the order the multimap was *populated*, since
    # within a bucket the order is insertion. Upstream populates it while walking trips in the
    # trip-id map's order, so a fingerprint's position is that of its earliest member. Handing
    # over `grouped` directly instead hands over the order stop_times.txt streamed in, which
    # for the seventeen-trip probe reorders three notices: measured, and the only difference
    # this whole rewrite made to any of 298 probe feeds.
    populated = sorted(grouped, key=lambda fingerprint: rank[grouped[fingerprint][0]["trip_id"]])

    groups = []
    for fingerprint in long_multimap_order(populated):
        members = grouped[fingerprint]
        # All trips in a group share a route id, since the fingerprint covers it.
        route = routes.get(members[0].get("route_id") or "")
        if route is None:
            continue
        groups.append(Group(trips=members, max_speed_kph=max_speed_kph(route.get("route_type"))))
    return stops, groups


def scan_rows(feed, stops: dict[str, dict], group: Group) -> tuple[list[dict], list[float]]:
    """The stop times upstream analyses for a group, and the hop distances over them.

    The first member's rows: upstream scans one trip per group and gives the findings to every
    member. Fetched per group rather than held on the Group, and measured here rather than
    stored, because both are the size of the group's trips and there can be a group per trip.
    """
    rows = rows_for_trip(feed, group.trips[0])
    return rows, hop_distances(stops, rows)


def rows_for_trip(feed, trip: dict) -> list[dict]:
    """One trips.txt row's stop times, in stop_sequence order."""
    return stop_time_trips.rows_for_trip(feed, trip["trip_id"])


def _first_by_id(feed, filename: str, column: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for row in feed.rows(filename):
        key = row.get(column)
        if key is not None:
            index.setdefault(key, row)
    return index


def max_speed_kph(route_type) -> float:
    return MAX_SPEED_KPH.get(route_type, DEFAULT_MAX_SPEED_KPH)


def coordinates(stops: dict[str, dict], row: dict) -> tuple[float, float] | None:
    """The stop time's coordinates, or None when the stop resolves to nothing.

    An unset stop_id reads as `""` through the getter, which is a lookup that finds nothing
    rather than a reason to skip the row earlier.
    """
    return stop_coordinates.optional_coordinates_of(stops, row.get(STOP_ID) or "")


def distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    """`S2Earth.getDistanceKm`, which is the metre distance divided by 1000."""
    return distance_meters(first[0], first[1], second[0], second[1]) / 1000.0


def hop_distances(stops: dict[str, dict], rows: list[dict]) -> list[float]:
    """`findDistancesKmBetweenStops`, including the two asymmetries it carries.

    The first stop goes through the *non*-optional lookup, so a trip whose first stop resolves
    to nothing measures its first hop from latitude 0, longitude 0 rather than skipping it.
    Every later stop goes through the optional one, and an unresolvable one contributes a
    distance of 0 **without** becoming the point the next hop is measured from.
    """
    distances = []
    current = stop_coordinates.coordinates_of(stops, rows[0].get(STOP_ID) or "")
    for index in range(len(rows) - 1):
        following = coordinates(stops, rows[index + 1])
        if following is None:
            distances.append(0.0)
            continue
        distances.append(distance_km(current, following))
        current = following
    return distances


def time_between(arrival: int, departure: int) -> int:
    """`getTimeBetweenStops`, whose two adjustments are both upstream's.

    Time that does not advance becomes a minute, which avoids dividing by zero and reporting a
    negative speed. Times that both land on a whole minute get a minute added, because a
    scheduling system writing minute resolution leaves up to 30 seconds of error either side.
    """
    elapsed = arrival - departure
    if elapsed <= 0:
        return SECONDS_PER_MINUTE
    if arrival % SECONDS_PER_MINUTE == 0 and departure % SECONDS_PER_MINUTE == 0:
        elapsed += SECONDS_PER_MINUTE
    return elapsed


def speed_kph(distance: float, start: dict, end: dict) -> float:
    """`getSpeedKphBetweenStops`: the distance over the time from one departure to the next
    arrival, which excludes however long the vehicle stands at the first stop."""
    return (
        distance * SECONDS_PER_HOUR / time_between(seconds(end, ARRIVAL), seconds(start, DEPARTURE))
    )


def seconds(row: dict, column: str) -> int:
    """The seconds a `GtfsTime` getter returns, which is 0 when the field is unset."""
    return row.get(column) or 0


def trip_fingerprint(route_id: str, stop_times: list[dict]) -> int:
    """`TripAndStopTimes.tripFprint()`, in the order Guava's `Hasher` was fed."""
    hasher = Hasher()
    hasher.put_int(utf16_length(route_id))
    hasher.put_unencoded_chars(route_id)
    hasher.put_int(len(stop_times))
    for stop_time in stop_times:
        stop_id = stop_time.get("stop_id") or ""
        hasher.put_int(utf16_length(stop_id))
        hasher.put_unencoded_chars(stop_id)
        hasher.put_int(seconds(stop_time, ARRIVAL))
        hasher.put_int(seconds(stop_time, DEPARTURE))
    return hasher.hash()


def pair_context(
    trip: dict,
    start: dict,
    start_stop: dict,
    end: dict,
    end_stop: dict,
    speed: float,
    distance: float,
) -> dict:
    """The context both notices carry, in the field order Gson wrote them in.

    The two notice classes declare the same fifteen fields, so this is one function rather
    than two identical ones. Which rows the callers pass is where they differ.
    """
    return {
        "tripCsvRowNumber": trip["_row_number"],
        "tripId": trip.get("trip_id") or "",
        "routeId": trip.get("route_id") or "",
        "speedKph": speed,
        "distanceKm": distance,
        "csvRowNumber1": start["_row_number"],
        "stopSequence1": start.get(SEQUENCE) or 0,
        "stopId1": start.get(STOP_ID) or "",
        "stopName1": start_stop.get("stop_name") or "",
        "departureTime1": hhmmss(seconds(start, DEPARTURE)),
        "csvRowNumber2": end["_row_number"],
        "stopSequence2": end.get(SEQUENCE) or 0,
        "stopId2": end.get(STOP_ID) or "",
        "stopName2": end_stop.get("stop_name") or "",
        "arrivalTime2": hhmmss(seconds(end, ARRIVAL)),
    }
