"""Names, key sets and the exceptions the locations.geojson parser raises.

Split out of the parser when it outgrew the file-size limit: these are the parts other
modules import, and keeping them here stops the CLI depending on the parser body.
"""

from __future__ import annotations

from gtfs_validator.schema import Field, FieldType, Presence, TableSchema

FILENAME = "locations.geojson"

# GtfsGeoJsonFeature's field-name constants. The dotted prefix is
# FEATURE_COLLECTION_FIELD_NAME, so a feature's missing id reports "features.id"
# rather than "id"; measured against the jar.
FEATURES = "features"
ROOT_KEYS = frozenset({"type", FEATURES})
FEATURE_KEYS = frozenset({"id", "type", "properties", "geometry"})
GEOMETRY_KEYS = frozenset({"type", "coordinates"})
FEATURE_COLLECTION_TYPE = "FeatureCollection"
FEATURE_TYPE = "Feature"
POLYGON_TYPES = frozenset({"Polygon", "MultiPolygon"})
# The nesting validateCoordinates assumes: an array of rings, each an array of
# positions, each a pair. Anything shallower makes upstream throw.
COORDINATE_DEPTH = 3


class DuplicateKey(Exception):
    """An object repeated a key, which json.loads would have silently dropped."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class UnparsableFeature(Exception):
    """One feature could not be read. The others are still examined."""


class DroppedFeature(Exception):
    """One feature upstream loses without saying anything about it.

    `validateCoordinates` runs before the geometry-type dispatch and indexes three levels
    down, so coordinates nested *deeper* than that make `points.get(0).getAsDouble()`
    throw into a bare `catch (Exception)` that only logs. A MultiPolygon is always four
    deep, so every MultiPolygon feature takes this path: measured on a feed whose only
    feature is a MultiPolygon with a bow-tie member, where the jar reports nothing at all
    and drops the location.

    The consequence is worth stating, because the code reads as though it were supported:
    `GeoJsonGeometryValidator.createMultiPolygon` exists, handles nested shells, and is
    **unreachable** through the file loader. Neither `invalid_geometry` nor
    `unsupported_geometry_type` can ever name a MultiPolygon.

    Distinct from UnparsableFeature: the file stays parsable and every other feature is
    still loaded and still reported on.
    """


class UnreadableGeoJson(Exception):
    """The file cannot be read at all, so the loader reports a system error.

    Distinct from UnparsableFeature, which is per feature and accumulates. This one
    covers what Gson throws out of the whole load: a coordinate array too shallow
    for validateCoordinates, or a scalar coercion getAsString refuses. Upstream
    swallows both in a bare catch that only logs; divergence 6 says we surface them,
    and until this existed we did not, so the entry described behaviour the code did
    not have.
    """


# locations.geojson is a @GtfsJson schema, which the table generator skips, so its shape is
# declared here rather than generated. What the parser keeps is what the cross-file rules read:
# `duplicate_geography_id` compares feature ids against stops and location groups and reports the
# feature's index rather than a row number, and `overlapping_zone_and_pickup_drop_off_window`
# compares two zones' geometry, which is why the rings are kept as well as their type.
#
# `_row_number` is set to the feature index so the store's machinery works unchanged. A GeoJSON
# feature has no CSV row and no notice reports one for it. What a feature notice carries instead
# varies: `featureIndex` for most, `firstIndex` and `secondIndex` for duplicate_geo_json_key, and
# nothing positional at all for some, so the index is stored rather than assumed to be the answer.
FEATURE_SCHEMA = TableSchema(
    filename=FILENAME,
    presence=Presence.OPTIONAL,
    primary_key=(),
    fields=(
        Field(name="feature_id", type=FieldType.ID, presence=Presence.REQUIRED),
        Field(name="feature_index", type=FieldType.INTEGER, presence=Presence.REQUIRED),
        Field(name="geometry_type", type=FieldType.TEXT, presence=Presence.REQUIRED),
        # The geometry's rings as JSON text. Upstream holds a parsed JTS `Geometry` on the
        # feature object instead; a rule that asks whether two zones overlap needs the rings to
        # rebuild one, and TEXT is the honest column type for a nested list. Adding to this is
        # not a generated-file edit, since this schema is hand-declared for the reason above.
        Field(name="coordinates", type=FieldType.TEXT, presence=Presence.OPTIONAL),
    ),
)
