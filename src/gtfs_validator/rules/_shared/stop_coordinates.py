"""`StopUtil.getStopOrParentLatLng`, the coordinate lookup that walks up a station tree.

A stop without its own `stop_lat`/`stop_lon` borrows its parent's, and a parent without them
borrows its own parent's. Three details are upstream's and none is a plain reading:

- The walk is **bounded at three lookups**, not recursive. Upstream says why in a comment: a feed
  can contain a cycle of parents, and this is called from a validator that must terminate.
- An unresolvable stop is not skipped, it becomes `S2LatLng.CENTER`, which is latitude 0,
  longitude 0. Measured: a transfer naming a stop that does not exist draws
  `transfer_distance_too_large` at 8568.438594310714 km, the distance from New York to the Gulf
  of Guinea. Skipping the row loses a notice the jar reports.
- Coordinates are taken only when **both** are present, since `hasStopLatLon()` is one test over
  the pair. A stop with a latitude and no longitude therefore borrows from its parent rather than
  measuring from the prime meridian.
"""

from __future__ import annotations

STOPS = "stops.txt"
LATITUDE = "stop_lat"
LONGITUDE = "stop_lon"
PARENT = "parent_station"
# S2LatLng.CENTER, which is what the lookup returns when it resolves nothing.
CENTER = (0.0, 0.0)
# Upstream's `for (int i = 0; i < 3; ++i)`, which bounds the walk against a parent cycle.
MAX_HOPS = 3


def stops_by_id(feed) -> dict[str, dict]:
    """The stops index, keeping the first row per id as upstream's generated index does."""
    stops: dict[str, dict] = {}
    for row in feed.rows(STOPS):
        stop_id = row.get("stop_id")
        if stop_id is not None:
            stops.setdefault(stop_id, row)
    return stops


def coordinates_of(stops: dict[str, dict], stop_id: str) -> tuple[float, float]:
    """The stop's own coordinates, an ancestor's within three hops, or (0, 0)."""
    return optional_coordinates_of(stops, stop_id) or CENTER


def optional_coordinates_of(stops: dict[str, dict], stop_id: str) -> tuple[float, float] | None:
    """`StopUtil.getOptionalStopOrParentLatLng`: None only when the walk resolved nothing.

    Upstream writes that filter as `s2LatLng != S2LatLng.CENTER`, which is a **reference**
    comparison against the constant the fallback returns. A stop whose file really gives
    latitude 0 and longitude 0 builds a different instance, compares unequal, and is measured.
    Distinguishing the two is what this function exists for: `coordinates_of` cannot, because
    both cases reach it as the same pair of zeroes. Measured on a feed whose second stop sits
    at the origin, which the jar reports as 8652.115181854942 km away rather than skipping.
    """
    for _ in range(MAX_HOPS):
        stop = stops.get(stop_id)
        if stop is None:
            break
        latitude, longitude = stop.get(LATITUDE), stop.get(LONGITUDE)
        if latitude is not None and longitude is not None:
            return (latitude, longitude)
        # `if (location.hasParentStation())`, so an empty parent_station is a hop rather
        # than the end of the walk. StopUtil.getStopOrParentLatLng, which every distance
        # and speed rule reads through.
        parent = stop.get(PARENT)
        if parent is None:
            break
        stop_id = parent
    return None
