"""The `invalid_geometry` half of stage 6: is this polygon valid, and what does JTS call it.

Two layers, because they fail differently. `validity` decides *which* of JTS's errors a
shape has, ported check by check and differentialled against the jar by
`tools/diff_geometry_against_jts.py`. The message *wording* is not ported at all: it is
generated from the pinned jar into `data/jts_messages.json`, because reading it was
measurably wrong three times over.

This module is the seam the GeoJSON parser uses: coordinates in, notice message out.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from gtfs_validator.geometry.validity import (
    Polygon,
    Ring,
    polygon_construction_message,
    validate_multipolygon,
    validate_polygon,
)

MULTI_POLYGON = "MultiPolygon"


@lru_cache(maxsize=1)
def _messages() -> dict[str, str]:
    raw = json.loads(files("gtfs_validator.data").joinpath("jts_messages.json").read_text())
    return raw["topology_errors"]


def _ring(coordinates: Any) -> Ring:
    """A ring's positions as (x, y) pairs, ignoring any third ordinate.

    Upstream reads `points.get(0)` and `points.get(1)` and never looks further, so an
    elevation is carried into neither the geometry nor the notice.
    """
    return [(float(point[0]), float(point[1])) for point in coordinates]


def _polygon(coordinates: Any) -> Polygon:
    return [_ring(ring) for ring in coordinates]


def geometry_message(geometry_type: str, coordinates: Any) -> str | None:
    """The `message` an invalid_geometry notice would carry, or None if the shape is valid.

    Construction is checked before validity and per ring, mirroring the order in
    `GeoJsonGeometryValidator`: `createLinearRing` throws before `IsValidOp` runs, and the
    notice then carries the exception's wording rather than a topology error's.
    """
    polygons = (
        [_polygon(polygon) for polygon in coordinates]
        if geometry_type == MULTI_POLYGON
        else [_polygon(coordinates)]
    )
    for polygon in polygons:
        message = polygon_construction_message(polygon)
        if message is not None:
            return message
    error = validate_polygon(polygons[0]) if len(polygons) == 1 else validate_multipolygon(polygons)
    return None if error is None else _messages()[error]
