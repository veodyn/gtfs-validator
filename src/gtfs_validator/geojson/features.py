"""The per-feature and per-geometry checks, and the notice helpers they share."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from gtfs_validator.geojson.constants import (
    COORDINATE_DEPTH,
    FEATURE_KEYS,
    FEATURE_TYPE,
    FILENAME,
    GEOMETRY_KEYS,
    POLYGON_TYPES,
    DroppedFeature,
    UnparsableFeature,
    UnreadableGeoJson,
)
from gtfs_validator.geojson.decoding import _as_string
from gtfs_validator.geometry import geometry_message
from gtfs_validator.notices import Notice, Severity


def _notice(code: str, severity: Severity, context: dict) -> Notice:
    return Notice(code, severity, context)


def _unknown_keys(obj: dict, expected: frozenset[str]) -> Iterator[Notice]:
    for key in obj:
        if key not in expected:
            yield _notice(
                "geo_json_unknown_element",
                Severity.INFO,
                {"filename": FILENAME, "unknownElement": key},
            )


def _missing(index: int | None, feature_id: str | None, element: str) -> Notice:
    """missing_required_element, omitting the keys upstream leaves null.

    Gson drops a null field, so the root-level call, which passes null for both the
    index and the id, produces a sample carrying only missingElement. Measured.
    """
    context: dict[str, object] = {}
    if index is not None:
        context["featureIndex"] = index
    if feature_id is not None:
        context["featureId"] = feature_id
    context["missingElement"] = element
    return _notice("missing_required_element", Severity.ERROR, context)


def _coordinate_depth(value: Any) -> int:
    """The shallowest nesting depth across *every* branch, not just the first.

    validateCoordinates walks the whole structure, so a ring list whose first ring
    is well formed and whose second is a scalar is still unreadable. Following
    value[0] alone accepted that.

    An empty list is the exception: the loop never indexes into it, so it cannot throw and
    cannot make the geometry unreadable. Treating it as depth zero rejected a polygon with
    an empty shell, which the jar builds and then refuses with its own message ("shell is
    empty but holes are not") when a hole is not empty, and accepts outright when no hole
    exists. Empty branches are therefore skipped rather than counted as shallow.
    """
    if not isinstance(value, list):
        return 0
    branches = [_coordinate_depth(item) for item in value if item != []]
    if not branches:
        return COORDINATE_DEPTH
    return 1 + min(branches)


# GeoJsonFileLoader.validateCoordinates' two bounds. Both are inclusive, measured: a point at
# exactly (1.0, 1.0) draws point_near_origin and one at exactly 89.0 degrees latitude draws
# point_near_pole.
ORIGIN_DEGREES = 1
POLE_DEGREES = 89


def _as_double(value: Any) -> float:
    """Gson's `JsonPrimitive.getAsDouble`, which parses a numeric string and throws on the rest.

    A JSON integer becomes a double, so the jar renders a coordinate of 0 as 0.0. A boolean
    throws, which Python's `isinstance(x, int | float)` would have accepted.
    """
    if isinstance(value, bool):
        raise UnreadableGeoJson("a coordinate is a boolean")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as error:
            raise UnreadableGeoJson("a coordinate is not a number") from error
    raise UnreadableGeoJson("a coordinate is not a number")


def _suspicious_points(coordinates: Any, index: int, feature_id: str | None) -> Iterator[Notice]:
    """point_near_origin and point_near_pole, one notice per coordinate pair.

    Per *pair*, not per distinct place: a ring repeats its first point as its last, and upstream
    reports that point twice. Measured on a four-point ring near the origin, which draws four
    notices with the first and last identical.

    The two are chained with `else if`, so the origin test wins, and the notice carries five of
    the eight fields the manifest declares. `csvRowNumber`, `latFieldName` and `lonFieldName` are
    left null by the constructor and Gson drops them.

    This runs *before* the geometry-type dispatch, which is observable: a LineString whose
    coordinates happen to be polygon-shaped and near a pole draws both these notices and
    unsupported_geometry_type. Measured.
    """
    if not isinstance(coordinates, list):
        raise UnreadableGeoJson("coordinates are not an array")
    for ring in coordinates:
        if not isinstance(ring, list):
            # Upstream *throws* here, on `coordinates.get(i).getAsJsonArray()`, and the notices
            # already emitted survive because they were added as the walk found them. So the walk
            # stops at the first unreadable ring rather than skipping it: a ring list of one good
            # ring followed by the scalar 5 reports that ring's four points and nothing after.
            # Measured on `geo_bad_ring`, where checking the depth up front emitted none of them.
            #
            # Raising rather than returning is the other half, which a review had to point out:
            # returning let the geometry-type dispatch run and emit an unsupported_geometry_type
            # the jar cannot reach, because upstream's throw leaves that code unreachable.
            raise UnreadableGeoJson("a ring is not an array")
        for point in ring:
            if not isinstance(point, list) or len(point) < 2:
                # `point.get(1)` on a one-element array throws, so the walk ends here and the
                # type dispatch never runs. Measured on a ring of four points whose third is
                # [0.3]: both sides report the two points before it and no geometry-type notice.
                raise UnreadableGeoJson("a coordinate pair is too short")
            # `getAsDouble()` parses a *string* primitive, so ["0.2","0.2"] is a coordinate pair
            # to Gson. It throws on a boolean, on a nested array and on a string that does not
            # parse. Both halves were wrong here: `isinstance(x, int | float)` admits a boolean,
            # because Python's bool subclasses int, and rejected the numeric strings Gson takes.
            longitude, latitude = _as_double(point[0]), _as_double(point[1])

            if abs(longitude) <= ORIGIN_DEGREES and abs(latitude) <= ORIGIN_DEGREES:
                code = "point_near_origin"
            elif abs(latitude) >= POLE_DEGREES:
                code = "point_near_pole"
            else:
                continue
            yield _notice(
                code,
                Severity.ERROR,
                {
                    "filename": FILENAME,
                    "featureIndex": index,
                    "entityId": feature_id,
                    "latFieldValue": latitude,
                    "lonFieldValue": longitude,
                },
            )


def _check_geometry(
    geometry: Any, index: int, feature_id: str | None, missing: list[str]
) -> Iterator[Notice]:
    """The geometry sub-checks, chained with elif exactly as upstream chains them.

    The chaining decides how many notices one feature draws: a geometry missing both
    `type` and `coordinates` reports only the type, because upstream's `else if`
    never reaches the second test.
    """
    if not isinstance(geometry, dict):
        raise UnparsableFeature(f"feature {index} geometry is not an object")
    yield from _unknown_keys(geometry, GEOMETRY_KEYS)
    if "type" not in geometry:
        missing.append("features.geometry.type")
        return
    if "coordinates" not in geometry:
        missing.append("features.geometry.coordinates")
        return
    if missing:
        # Upstream only validates the geometry when every required field is present.
        return
    # Before the depth checks, because upstream's validateCoordinates emits as it walks and
    # only then throws on the element it cannot read.
    yield from _suspicious_points(geometry["coordinates"], index, feature_id)
    if _coordinate_depth(geometry["coordinates"]) < COORDINATE_DEPTH:
        # What upstream's validateCoordinates throws on, before it reaches the
        # geometry-type dispatch. See divergence 6: upstream swallows this and
        # reports nothing at all, so unsupported_geometry_type is unreachable for a
        # Point or a LineString.
        raise UnreadableGeoJson(
            f"feature {index} coordinates are nested {_coordinate_depth(geometry['coordinates'])} "
            f"deep, expected {COORDINATE_DEPTH}"
        )
    if _coordinate_depth(geometry["coordinates"]) > COORDINATE_DEPTH:
        # Deeper than validateCoordinates indexes, so upstream throws and swallows before
        # the type dispatch. See DroppedFeature: this is every MultiPolygon.
        raise DroppedFeature(f"feature {index} coordinates are nested deeper than expected")
    geometry_type = _as_string(geometry["type"])
    if geometry_type not in POLYGON_TYPES:
        yield _notice(
            "unsupported_geometry_type",
            Severity.ERROR,
            {"featureIndex": index, "featureId": feature_id, "geometryType": geometry_type},
        )
        return
    message = geometry_message(geometry_type, geometry["coordinates"])
    if message is not None:
        # The notice first, then the feature is lost: `createPolygon` emits from inside itself
        # and returns null, and the loader answers `if (polygon == null) return null;`, which
        # sets hasUnparsableFeature and makes the *whole file* unparsable. One bad ring
        # therefore costs every feature in the file. Measured on a feed whose third zone is a
        # bow-tie, where the jar reports invalid_geometry and no
        # overlapping_zone_and_pickup_drop_off_window for the two valid zones that plainly
        # overlap; keeping the feature reported that pair and diverged.
        yield _notice(
            "invalid_geometry",
            Severity.ERROR,
            {
                "featureId": feature_id,
                "featureIndex": index,
                "geometryType": geometry_type,
                "message": message,
            },
        )
        raise UnparsableFeature(f"feature {index} has an invalid geometry")


def _check_feature(feature: Any, index: int) -> Iterator[Notice]:
    """extractFeature, transcribed. Yields notices; raises if the feature is lost."""
    if not isinstance(feature, dict):
        raise UnparsableFeature(f"feature {index} is not an object")
    yield from _unknown_keys(feature, FEATURE_KEYS)

    missing: list[str] = []
    feature_id: str | None = None
    if "id" not in feature:
        missing.append("features.id")
    else:
        # Assigned before the emptiness test, so a blank id is reported as "" while
        # an absent one omits the key entirely. Both states are measured.
        feature_id = _as_string(feature["id"])
        if not feature_id:
            missing.append("features.id")

    if "type" not in feature:
        missing.append("features.type")
    elif _as_string(feature["type"]) != FEATURE_TYPE:
        # The generated manifest lists this code with no context fields and the jar
        # emits three. The jar wins, as it did for missing_stop_name's locationType.
        yield _notice(
            "unsupported_feature_type",
            Severity.ERROR,
            {
                "featureIndex": index,
                "featureId": feature_id,
                "featureType": _as_string(feature["type"]),
            },
        )

    if "properties" not in feature:
        missing.append("features.properties")

    if "geometry" not in feature:
        missing.append("features.geometry")
    else:
        yield from _check_geometry(feature["geometry"], index, feature_id, missing)

    for element in missing:
        yield _missing(index, feature_id, element)
    if missing:
        raise UnparsableFeature(f"feature {index} is missing {', '.join(missing)}")
