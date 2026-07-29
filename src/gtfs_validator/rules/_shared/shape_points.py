"""The consecutive-pair walk all four ShapeIncreasingDistanceValidator codes share.

One upstream validator, four codes, decided in a single pass over each shape's points in
`shape_pt_sequence` order. The checklist for a shared source applies:

- **Order.** Shapes come out in the order `Multimaps.asMap(table.byShapeIdMap())` yields, which
  is `multimap_order` and **not** `hashmap_order`. A generated container indexes with
  `ArrayListMultimap.create()`, pre-sized for 12 keys, so its table starts at 32 buckets where a
  plain `HashMap` starts at 16. Measured two ways, because the first way could not see it: on a
  1,005-shape feed both orders agree with the jar for all 1,000 samples, since by then the maps
  have resized to a common capacity, and on a 2-shape feed carrying 2,002 notices only
  `multimap_order` does.
- **Gates.** All four depend on shapes.txt alone, so they are silenced together when it fails.
- **Disagreement.** The four branches are mutually exclusive per pair. They do **not** cover
  every pair carrying two distances, and an earlier version of this said they did: an increasing
  pair draws nothing, which is the ordinary case, and so does a pair whose coordinates differ
  while the haversine underflows to 0, since the coordinate test is exact equality and the
  remaining branch needs `> 0`. Both were confirmed silent on the jar as well as here.

The pairs are *adjacent in sequence*, and a point with no `shape_dist_traveled` is not skipped
over: it suppresses the two pairs it belongs to rather than letting the rows either side of it
form one. Measured on a three-point shape whose middle distance is blank, where the outer values
do decrease and the jar reports nothing.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.javahash import multimap_order
from gtfs_validator.s2earth import distance_meters

SHAPES = "shapes.txt"
DISTANCE = "shape_dist_traveled"
SEQUENCE = "shape_pt_sequence"
LATITUDE = "shape_pt_lat"
LONGITUDE = "shape_pt_lon"
_CACHE_KEY = "shape_points.by_shape"


def by_shape(feed) -> dict[str, list[dict]]:
    """Each shape's points in `shape_pt_sequence` order, keyed in HashMap order.

    A point with no sequence is dropped: the column is required, so such a row failed typing
    and upstream never sees it.
    """
    cached = feed.cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    grouped: dict[str, list[dict]] = {}
    for row in feed.rows(SHAPES):
        shape_id, sequence = row.get("shape_id"), row.get(SEQUENCE)
        if shape_id is None or sequence is None:
            continue
        grouped.setdefault(shape_id, []).append(row)
    for points in grouped.values():
        points.sort(key=lambda row: (row[SEQUENCE], row["_row_number"]))
    ordered = {shape_id: grouped[shape_id] for shape_id in multimap_order(grouped)}
    feed.cache[_CACHE_KEY] = ordered
    return ordered


def measured_pairs(feed) -> Iterator[tuple[dict, dict]]:
    """Consecutive point pairs, in report order, where both carry a `shape_dist_traveled`."""
    for points in by_shape(feed).values():
        for index in range(1, len(points)):
            previous, current = points[index - 1], points[index]
            if previous.get(DISTANCE) is None or current.get(DISTANCE) is None:
                continue
            yield previous, current


def equal_distance_differing_points(feed) -> Iterator[tuple[dict, dict, dict]]:
    """Pairs claiming one distance at two different places, with their shared context.

    The precondition the two distance-reporting codes split on, held in one place so the pair
    of them cannot drift apart on which pairs they consider. The coordinate test is exact
    equality on both fields, as upstream's is, so a pair one nanometre apart arrives here
    rather than at the same-coordinates code.
    """
    for previous, current in measured_pairs(feed):
        if previous[DISTANCE] != current[DISTANCE]:
            continue
        if current[LATITUDE] == previous[LATITUDE] and current[LONGITUDE] == previous[LONGITUDE]:
            continue
        yield previous, current, pair_context(current, previous)


def distance_between(previous: dict, current: dict) -> float:
    """`S2Earth.getDistanceMeters` over the pair, in upstream's argument order.

    The haversine is symmetric, so the order does not change the value. Keeping it makes the
    line checkable against the Java without a reader having to know that.
    """
    return distance_meters(
        current[LATITUDE], current[LONGITUDE], previous[LATITUDE], previous[LONGITUDE]
    )


def pair_context(named: dict, prefixed: dict) -> dict:
    """The seven fields every one of the four notices carries.

    The parameters are the two *roles*, not the two positions in the shape: `named` fills
    `csvRowNumber` and its siblings, `prefixed` fills the `prev`-prefixed ones. Which point
    plays which role is the caller's business, because upstream is not consistent about it.
    Three codes pass `(later, earlier)`; `decreasing_shape_distance` passes `(earlier, later)`,
    reproducing a swap in upstream's own constructor call. Naming these `earlier`/`later` here
    would bake one caller's convention into a helper the other three also use.
    """
    return {
        "shapeId": named["shape_id"],
        "csvRowNumber": named["_row_number"],
        "shapeDistTraveled": named[DISTANCE],
        "shapePtSequence": named[SEQUENCE],
        "prevCsvRowNumber": prefixed["_row_number"],
        "prevShapeDistTraveled": prefixed[DISTANCE],
        "prevShapePtSequence": prefixed[SEQUENCE],
    }
