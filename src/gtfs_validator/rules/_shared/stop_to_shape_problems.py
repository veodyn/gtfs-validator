"""`ShapeToStopMatchingValidator`: one pass over the feed, four notice codes out of it.

The four codes cannot be computed independently. They come out of a single walk that carries state
across trips and across both matching passes, and two pieces of that state are what makes the walk
indivisible:

- **`reported_stop_ids`** suppresses a repeat of the too-far kind for a stop already named, across
  every trip on the shape *and* across both distance passes. So whether the user-distance code
  fires depends on what the geo pass already reported. Measured on the sm2 probe, where both passes
  find the same stop too far and only the geo code appears.
- **`processed_trip_hashes`** skips a trip whose stop pattern a previous trip already matched, so
  the notices name the first such trip and no other.

Each rule module filters this list for its own code, in this order, so the four codes agree about
which trip and which stop they name.
"""

from __future__ import annotations

from gtfs_validator.farmhash import Hasher
from gtfs_validator.javatext import utf16_length
from gtfs_validator.rules._shared import shape_points, stop_coordinates, stop_time_trips
from gtfs_validator.s2point import to_lat_lng_degrees
from gtfs_validator.stop_to_shape.matcher import match_using_geo_distance, match_using_user_distance
from gtfs_validator.stop_to_shape.matches import Match, Problem, ProblemType
from gtfs_validator.stop_to_shape.shape import ShapePoints
from gtfs_validator.stop_to_shape.stops import StopPoints, large_stations_for_route_type

STOPS = "stops.txt"
TRIPS = "trips.txt"
ROUTES = "routes.txt"
STOP_TIMES = "stop_times.txt"
SHAPES = "shapes.txt"

TOO_FAR = "stop_too_far_from_shape"
TOO_FAR_USER_DISTANCE = "stop_too_far_from_shape_using_user_distance"
TOO_MANY_MATCHES = "stop_has_too_many_matches_for_shape"
OUT_OF_ORDER = "stops_match_shape_out_of_order"

_CACHE_KEY = "stop_to_shape.problems"


def problems(feed) -> list[tuple[str, dict]]:
    """Every notice this validator produces, as (code, context) in emission order."""
    cached = feed.cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    found = list(_walk(feed))
    feed.cache[_CACHE_KEY] = found
    return found


def contexts_for(feed, code: str) -> list[dict]:
    return [context for found, context in problems(feed) if found == code]


def _walk(feed):
    """The validator's own loop: shape, then trip, then the two matching passes."""
    # `getEntities().isEmpty()` on all four tables. Not a dependency gate: these are tables that
    # loaded correctly and hold nothing, which upstream still refuses to match against. shapes.txt
    # is tested through the grouping so the table is read once.
    by_shape = shape_points.by_shape(feed)
    if not by_shape or _is_empty(feed, STOPS) or _is_empty(feed, STOP_TIMES):
        return
    stops = stop_coordinates.stops_by_id(feed)
    route_types = _route_types(feed)

    for shape_id, rows in by_shape.items():
        # Streamed, not collected. A feed where every trip names the same shape would put the whole
        # of trips.txt in memory, and one where every trip names none would too. `ShapePoints` is
        # built lazily on the first trip for the same reason: a feed carrying many unused shapes
        # should not pay to convert their coordinates.
        shape = None
        processed_trip_hashes: set[int] = set()
        reported_stop_ids: set[str] = set()
        for trip in _trips_for_shape(feed, shape_id):
            if shape is None:
                shape = ShapePoints.from_rows(rows)
            # Both sets are per shape, so the same stop can be reported once for each shape it is
            # too far from. They are reset above the trip loop rather than outside the shape loop,
            # which is upstream's placement.
            stop_times = stop_time_trips.rows_for_trip(feed, trip.get("trip_id", ""))
            fingerprint = _trip_hash(stop_times)
            if fingerprint in processed_trip_hashes:
                continue
            processed_trip_hashes.add(fingerprint)
            route_id = trip.get("route_id")
            if route_id not in route_types:
                # A broken route reference is another rule's notice, and this one goes quiet rather
                # than matching against a route type it does not have.
                continue
            stop_points = StopPoints.from_stop_times(
                stop_times, stops, large_stations_for_route_type(route_types[route_id])
            )
            yield from _report(
                feed,
                trip,
                match_using_geo_distance(stop_points, shape).problems,
                stops,
                reported_stop_ids,
                user_distance=False,
            )
            if stop_points.has_user_distance() and shape.has_user_distance():
                yield from _report(
                    feed,
                    trip,
                    match_using_user_distance(stop_points, shape).problems,
                    stops,
                    reported_stop_ids,
                    user_distance=True,
                )


def _report(feed, trip, found, stops, reported_stop_ids, *, user_distance):
    """Turn one pass's problems into (code, context) pairs, applying the two suppressions."""
    for problem in found:
        stop_id = problem.stop_time.get("stop_id")
        # `stopId().isEmpty()`, so an absent stop_id and an empty one are both skipped. This is a
        # value test rather than a presence test, which is why it stays truthiness.
        if not stop_id:
            continue
        if problem.type is ProblemType.STOP_TOO_FAR_FROM_SHAPE:
            if stop_id in reported_stop_ids:
                continue
            reported_stop_ids.add(stop_id)
        yield _context(trip, problem, stops, user_distance=user_distance)


def _context(trip, problem: Problem, stops, *, user_distance: bool) -> tuple[str, dict]:
    """The notice code and its context fields, in the order the Java declares them."""
    # Every id here is a Java `String`, so an unset one renders as "" rather than as null or as an
    # omitted key. `shapeId` is the one that shows it: a trip with no `shape_id` column at all is
    # matched against a shape whose own id is empty, and the jar reports "" for it. Measured on
    # `quoted_whitespace_shape_id.zip`, where reporting None put a JSON null in the field.
    shared = {
        "tripCsvRowNumber": trip["_row_number"],
        "shapeId": trip.get("shape_id") or "",
        "tripId": trip.get("trip_id") or "",
    }
    if problem.type is ProblemType.STOPS_MATCH_OUT_OF_ORDER:
        return (
            OUT_OF_ORDER,
            {
                **shared,
                **_stop_fields(problem.stop_time, problem.match, stops, suffix="1"),
                **_stop_fields(
                    problem.previous_stop_time, problem.previous_match, stops, suffix="2"
                ),
            },
        )
    fields = {**shared, **_stop_fields(problem.stop_time, problem.match, stops, suffix="")}
    if problem.type is ProblemType.STOP_HAS_TOO_MANY_MATCHES:
        return (TOO_MANY_MATCHES, {**fields, "matchCount": problem.match_count})
    code = TOO_FAR_USER_DISTANCE if user_distance else TOO_FAR
    return (code, {**fields, "geoDistanceToShape": problem.match.geo_distance_to_shape})


def _stop_fields(stop_time: dict, match: Match, stops: dict, *, suffix: str) -> dict:
    """The four fields naming one stop: its row, id, name and matched location.

    The name is the stop's **own** `stop_name` and does not walk up to a parent station, unlike the
    coordinates the matching used. So a boarding area with no name of its own reports an empty
    name while being matched at its parent's location.
    """
    stop_id = stop_time.get("stop_id") or ""
    stop = stops.get(stop_id)
    latitude, longitude = to_lat_lng_degrees(match.location)
    return {
        f"stopTimeCsvRowNumber{suffix}": stop_time["_row_number"],
        f"stopId{suffix}": stop_id,
        f"stopName{suffix}": "" if stop is None else (stop.get("stop_name") or ""),
        # Serialized as a two-element array, latitude first: measured, not assumed, since an
        # S2LatLng holds radians and reports degrees.
        f"match{suffix}": [latitude, longitude],
    }


def _trip_hash(stop_times: list[dict]) -> int:
    """`ShapeToStopMatchingValidator.tripHash`: the fingerprint that collapses identical trips.

    A tuple key would collapse the same trips in every case a 64-bit fingerprint does, and the
    fingerprint is ported anyway because it is cheap next to the geometry and because a collision
    is the one case where the two differ: upstream would skip a trip we would match.

    The id's length is counted in UTF-16 code units, so an id holding an emoji contributes more
    than its character count, and an unset `shape_dist_traveled` contributes eight bytes of zero
    rather than being skipped.
    """
    hasher = Hasher().put_int(len(stop_times))
    for stop_time in stop_times:
        stop_id = stop_time.get("stop_id") or ""
        distance = stop_time.get("shape_dist_traveled")
        hasher.put_int(utf16_length(stop_id)).put_unencoded_chars(stop_id).put_double(
            0.0 if distance is None else distance
        )
    return hasher.hash()


def _trips_for_shape(feed, shape_id: str):
    """The trips referencing this shape, in file order, one at a time.

    Read per shape rather than from a whole-table grouping, and yielded rather than collected: a
    feed can carry more trips than fit comfortably in memory, one shape can be named by all of
    them, and the index makes the ordinary case a seek.

    **A trip with no `shape_id` at all is keyed under the empty string.** `GtfsTrip.shapeId()`
    returns the type default for an unset field and the generated container indexes on that, so a
    shape whose own id is empty collects every trip that names no shape. Measured on
    `quoted_whitespace_shape_id.zip`, a feed whose `trips.txt` has no `shape_id` column and whose
    `shapes.txt` id is a quoted whitespace cell that the loader stores as "": the jar reports
    `stop_too_far_from_shape` and a lookup keyed on the stored value alone reports nothing.

    That case takes a scan instead of a seek, because a SQL `= ''` cannot match a NULL. It costs a
    scan of `trips.txt` only for a feed carrying a shape with an empty id, which is malformed.
    """
    if shape_id != "":
        yield from feed.rows_where(TRIPS, "shape_id", shape_id)
        return
    for row in feed.rows(TRIPS):
        if not row.get("shape_id"):
            yield row


def _route_types(feed) -> dict[str, object]:
    """`route_type` per route id, keeping the first row per id as the generated index does."""
    types: dict[str, object] = {}
    for row in feed.rows(ROUTES):
        route_id = row.get("route_id")
        if route_id is not None and route_id not in types:
            types[route_id] = row.get("route_type")
    return types


def _is_empty(feed, filename: str) -> bool:
    return next(iter(feed.rows(filename)), None) is None
