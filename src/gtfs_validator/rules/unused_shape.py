"""ShapeUsageValidator: a shape no trip refers to.

Reported once per shape, at the row where it first appears: upstream guards on
`reportedShapes.add(shapeId)`, which is true only the first time, so a shape with
fifty points draws one notice naming its first row rather than fifty or its last.

Measured on a shapes.txt of SH_ONE (row 2, unreferenced), SH_MANY (rows 3 to 5,
referenced by a trip) and SH_ALSO (row 6, unreferenced): two notices, at rows 2
and 6.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule


@file_rule(code="unused_shape", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # A trip with no shape_id refers to the *empty* shape id, not to nothing. The generated
    # index runs `byShapeIdMap.put(entity.shapeId(), entity)` with no presence guard, and an
    # unset String field reads as "", so every trip lacking the column lands under "" and a
    # shape whose id is empty counts as used. Measured on a feed whose shapes.txt carries a
    # quoted whitespace shape_id, trimmed to "", and whose trips.txt has no shape_id column:
    # the jar reports no unused_shape, and skipping those trips reported one.
    used = {row.get("shape_id") or "" for row in feed.rows("trips.txt")}
    reported: set[str] = set()
    for point in feed.rows("shapes.txt"):
        shape_id = point.get("shape_id")
        if shape_id is None or shape_id in reported:
            continue
        reported.add(shape_id)
        if shape_id in used:
            continue
        yield Notice(
            "unused_shape",
            Severity.WARNING,
            {"shapeId": shape_id, "csvRowNumber": point["_row_number"]},
        )
