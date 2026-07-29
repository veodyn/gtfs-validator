"""The generated per-table lat/lon check, which is the *other* source of the point-near codes.

`point_near_origin` and `point_near_pole` have two upstream sources, and the second is easy to
miss because it does not exist in the source tree: `LatLonValidatorGenerator` emits a
`SingleEntityValidator` per table with a lat/lon pair, so grepping the validator package finds
only `GeoJsonFileLoader`. Two tables qualify at the pin, stops.txt and shapes.txt.

The two sources differ in three ways, all measured:

| | generated CSV validator | GeoJsonFileLoader |
|---|---|---|
| structure | two separate `if`s | `if` / `else if` |
| gate | `hasStopLatLon()`, both fields present | every required feature field present |
| context | `csvRowNumber`, `latFieldName`, `lonFieldName` | `featureIndex` |

`entityId` appears in both, but only when the table has a **single-column** primary key: the
generator adds it from `getSingleColumnPrimaryKey()`, so a stops.txt notice carries `entityId` and
a shapes.txt one does not, its key being (shape_id, shape_pt_sequence). Measured on both.

Being a SingleEntityValidator, it runs per row *during* loading, so it reads `entity_rows` and
survives a table whose load later fails.
"""

from __future__ import annotations

from collections.abc import Iterator

# The same two bounds as the GeoJSON scan, and inclusive for the same reason.
ORIGIN_DEGREES = 1.0
POLE_DEGREES = 89.0


def suspicious_rows(
    feed, filename: str, latitude_field: str, longitude_field: str, key_field: str | None
) -> Iterator[tuple[str, dict]]:
    """Each row whose coordinates sit near the origin or a pole, with its notice context.

    Yields `(code, context)` and can yield *both* codes for one row: the generated validator
    writes two separate `if` statements where the GeoJSON loader chains them with `else`. No
    coordinate satisfies both, so this is faithfulness rather than a reachable difference.
    """
    for row in feed.entity_rows(filename):
        latitude, longitude = row.get(latitude_field), row.get(longitude_field)
        # `hasStopLatLon()` is one test over the pair, so a row with only one is skipped.
        if latitude is None or longitude is None:
            continue
        context = {"filename": filename, "csvRowNumber": row["_row_number"]}
        if key_field is not None:
            context["entityId"] = row.get(key_field)
        context |= {
            "latFieldName": latitude_field,
            "latFieldValue": latitude,
            "lonFieldName": longitude_field,
            "lonFieldValue": longitude,
        }
        if abs(latitude) <= ORIGIN_DEGREES and abs(longitude) <= ORIGIN_DEGREES:
            yield "point_near_origin", dict(context)
        if abs(latitude) >= POLE_DEGREES:
            yield "point_near_pole", dict(context)


# The tables the generator produces a validator for, with the key that becomes entityId.
LAT_LON_TABLES = (
    ("stops.txt", "stop_lat", "stop_lon", "stop_id"),
    ("shapes.txt", "shape_pt_lat", "shape_pt_lon", None),
)
