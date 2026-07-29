"""SingleShapePointValidator: a shape defined by one point is not a line.

Counts points per shape_id and reports the shapes with exactly one, naming that
point's row. Measured: a shapes.txt holding one single-point shape, one three-point
shape and a second single-point shape draws two notices, for the two singletons.

Upstream reports these in `HashMap` order, and that *is* part of the contract: above the
1,000-sample cap the order decides which notices a report keeps. This docstring used to say
the opposite, and both halves of it were wrong. The code was corrected when a 1,005-shape
probe showed the jar's samples beginning SH0809, SH0808, SH0807; the docstring was not, so
it went on contradicting the `hashmap_order` call three lines below it.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import hashmap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule


@file_rule(code="single_shape_point", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    counts: dict[str, int] = {}
    rows: dict[str, int] = {}
    for point in feed.rows("shapes.txt"):
        shape_id = point.get("shape_id")
        if shape_id is None:
            continue
        counts[shape_id] = counts.get(shape_id, 0) + 1
        # Overwritten per point, as upstream's put is, so this is the last row seen.
        # For a shape with one point that is also its only row.
        rows[shape_id] = point["_row_number"]
    for shape_id in hashmap_order(counts):
        if counts[shape_id] != 1:
            continue
        yield Notice(
            "single_shape_point",
            Severity.WARNING,
            {"shapeId": shape_id, "csvRowNumber": rows[shape_id]},
        )
