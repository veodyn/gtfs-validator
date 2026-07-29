"""OverlappingPickupDropOffZoneValidator: two demand-responsive zones booked at once.

A flex trip's stop times name zones in `locations.geojson` rather than stops, each with a window
you can be picked up in. Two rows of one trip whose windows overlap *and* whose zones overlap
describe a vehicle asked to serve two areas at the same time.

Four gates, and every one of them is a way for the jar to stay quiet:

- **The types.** The condition is `pickup1 != pickup2 && dropOff1 != dropOff2`, so a pair is
  skipped only when *both* differ. Matching on drop-off alone is still a notice, which a reading
  of "the types must match" loses. An `UNRECOGNIZED` type in either row skips the pair outright.
- **The fields.** All four window ends and both location ids must be set, tested with the
  `has` accessors rather than defaulted.
- **The windows.** Strict overlap: `start1 > end2`, `end1 < start2`, and *equality* at either
  end are all skipped, so windows that merely touch are not overlapping.
- **The zones.** JTS `overlaps`, which is where this rule's reputation for being quiet comes
  from. Containment is not overlap, a shared edge is not overlap, and two identical zones do not
  overlap. See `gtfs_validator.geometry.overlaps`; all three are measured against the jar.

Trips come out in `multimap_order` and each trip's pairs in stop_sequence order, since the
container hands the validator a sequence-ordered list per trip.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.geometry.overlaps import polygons_overlap, to_exact
from gtfs_validator.javahash import multimap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import stop_time_trips
from gtfs_validator.rules._shared.render import hhmmss
from gtfs_validator.rules.registry import file_rule

CODE = "overlapping_zone_and_pickup_drop_off_window"
GEOJSON = "locations.geojson"
STOP_TIMES = "stop_times.txt"
LOCATION_ID = "location_id"
START = "start_pickup_drop_off_window"
END = "end_pickup_drop_off_window"
PICKUP = "pickup_type"
DROP_OFF = "drop_off_type"
REQUIRED = (START, END, LOCATION_ID)
# The two enum values that are not a service kind. An *absent* pickup_type is REGULAR, because
# the generated getter returns the enum's zero for an unset field, and an unparsable one is
# UNRECOGNIZED, which the store keeps as -1. Those are opposite answers and this rule had them
# the wrong way round: two rows with both fields blank were being skipped as unrecognised, where
# the jar defaults them to REGULAR, finds them equal and reports the pair.
REGULAR = 0
UNRECOGNIZED = -1
# Only a Polygon carries a geometry. Upstream builds its JTS geometry inside the type dispatch,
# so a feature whose type it calls unsupported reaches the container with a *null* geometry and
# `geometryOverlaps` answers false for it. Measured: a feature typed "Hexagon" with a ring that
# plainly overlaps its neighbour draws nothing from the jar.
POLYGON = "Polygon"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # `if (stopTimeTable.isMissingFile() || geoJsonFeatures.isMissingFile()) return;`. Not an
    # optimisation dressed up as parity, though it is also worth 7 seconds on the scale feed: an
    # ordinary scheduled feed has no locations.geojson at all, and without this the rule compared
    # 1.74 million stop time pairs to look each one up in an empty zone index. The answer was the
    # same and the work was not, which is the shape of thing a differential can never show.
    if feed.is_missing(STOP_TIMES) or feed.is_missing(GEOJSON):
        return
    zones = _zones(feed)
    for trip_id in multimap_order(stop_time_trips.trip_ids(feed)):
        rows = stop_time_trips.rows_for_trip(feed, trip_id)
        for index, first in enumerate(rows):
            for second in rows[index + 1 :]:
                if _reportable(first, second, zones):
                    yield Notice(CODE, Severity.ERROR, _context(trip_id, first, second))


def _zones(feed) -> dict[str, list]:
    """Each feature's rings by location id, as exact rings ready to compare.

    Read once for the feed. A zone is named by many stop times, and converting its rings per
    comparison would redo the same work for every pair that mentions it.

    **First feature wins** on a duplicate id, which is `setdefault` rather than assignment. The
    container upstream builds keeps the first, and the difference is observable whenever a file
    declares an id twice: measured on a feed whose first `D1` overlaps its neighbour and whose
    second is twenty degrees away, where the jar reports the pair. The duplicate itself is
    `duplicate_geo_json_key`, another rule's notice.

    Only a Polygon is kept. See `POLYGON`.
    """
    zones: dict[str, list] = {}
    for row in feed.rows(GEOJSON):
        raw = row.get("coordinates")
        if raw is None or row.get("geometry_type") != POLYGON:
            continue
        zones.setdefault(row.get("feature_id") or "", to_exact(json.loads(raw)))
    return zones


def _reportable(first: dict, second: dict, zones: dict[str, list]) -> bool:
    if not _types_allow(first, second):
        return False
    if any(row.get(field) is None for row in (first, second) for field in REQUIRED):
        return False
    if first[LOCATION_ID] == second[LOCATION_ID]:
        return False
    if not _windows_overlap(first, second):
        return False
    shapes = [zones.get(row[LOCATION_ID]) for row in (first, second)]
    if any(shape is None for shape in shapes):
        # A stop time naming a zone no feature declares. The broken reference is another
        # rule's notice, and upstream's lookup simply returns null here.
        return False
    return polygons_overlap(shapes[0], shapes[1])


def _types_allow(first: dict, second: dict) -> bool:
    """`!(p1 != p2 && d1 != d2) && nothing UNRECOGNIZED`, kept in that shape deliberately.

    Written as its own function because the `&&` is the part a reader gets wrong: the pair is
    dropped only when both the pickup types and the drop-off types differ. The other trap is one
    level down, in what an *unset* field means; see `_service_kind`.
    """
    kinds = [[_service_kind(row, field) for field in (PICKUP, DROP_OFF)] for row in (first, second)]
    if any(kind == UNRECOGNIZED for row in kinds for kind in row):
        return False
    return kinds[0][0] == kinds[1][0] or kinds[0][1] == kinds[1][1]


def _service_kind(row: dict, field: str) -> int:
    """The enum the generated getter returns: REGULAR for an unset field, else what was stored.

    An absent value is not an unknown value. Upstream's getter answers with the enum's zero for a
    field the row never carried, and only a value it could not parse becomes UNRECOGNIZED.
    """
    value = row.get(field)
    return REGULAR if value is None else value


def _windows_overlap(first: dict, second: dict) -> bool:
    """Strict overlap, with equality at either end excluded as upstream excludes it."""
    first_start, first_end = first[START], first[END]
    second_start, second_end = second[START], second[END]
    if first_start > second_end or first_end < second_start:
        return False
    return not (first_end == second_start or first_start == second_end)


def _context(trip_id: str, first: dict, second: dict) -> dict:
    return {
        "tripId": trip_id,
        "stopSequence1": first.get("stop_sequence"),
        "locationId1": first[LOCATION_ID],
        "startPickupDropOffWindow1": hhmmss(first[START]),
        "endPickupDropOffWindow1": hhmmss(first[END]),
        "stopSequence2": second.get("stop_sequence"),
        "locationId2": second[LOCATION_ID],
        "startPickupDropOffWindow2": hhmmss(second[START]),
        "endPickupDropOffWindow2": hhmmss(second[END]),
    }
