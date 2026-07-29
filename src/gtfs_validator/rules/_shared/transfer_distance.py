"""The measured transfer walk both TransferDistanceValidator codes share.

One validator, two codes, one pass over transfers.txt in file order. The shared-source checklist:

- **Order.** File order over `getEntities()`, with no map involved, so neither `hashmap_order` nor
  `multimap_order` applies here.
- **Gates.** transfers.txt and stops.txt are both injected, so a failure in either silences both
  codes. Reading both tables here is what reproduces that.
- **Disagreement.** The bands are exclusive and tested in the order `> 10_000` then `> 2_000`, so
  a transfer over 10 km draws only the second code and one of exactly 2,000 m draws neither.

Both ends must be present: `hasFromStopId() && hasToStopId()` gates the loop. That is not the same
as both ends being *resolvable*, and the difference is measurable. A blank end skips the row; an
end naming a stop that does not exist is measured from latitude 0, longitude 0.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.rules._shared.stop_coordinates import coordinates_of, stops_by_id
from gtfs_validator.s2earth import point_distance_meters

TRANSFERS = "transfers.txt"
FROM_STOP = "from_stop_id"
TO_STOP = "to_stop_id"
# TransferDistanceValidator's two bounds, in metres, while the notice reports kilometres.
ABOVE_2KM_METERS = 2_000
TOO_LARGE_METERS = 10_000


def measured_transfers(feed) -> Iterator[tuple[dict, float]]:
    """Each transfer naming both ends, with the distance between them in metres."""
    stops = stops_by_id(feed)
    for row in feed.rows(TRANSFERS):
        from_stop, to_stop = row.get(FROM_STOP), row.get(TO_STOP)
        if from_stop is None or to_stop is None:
            continue
        first = coordinates_of(stops, from_stop)
        second = coordinates_of(stops, to_stop)
        # The S2Point overload, not the haversine: the validator calls .toPoint() first.
        yield row, point_distance_meters(first[0], first[1], second[0], second[1])


def distance_context(row: dict, distance_meters: float) -> dict:
    """The four fields both notices carry, with the distance converted as upstream converts it."""
    return {
        "csvRowNumber": row["_row_number"],
        "fromStopId": row[FROM_STOP],
        "toStopId": row[TO_STOP],
        # `distanceMeters / 1_000`, computed the same way round so the division rounds alike.
        "distanceKm": distance_meters / 1_000,
    }
