"""Stage 6: parse locations.geojson and emit its structural notices.

A separate parser rather than a CSV table, mirroring upstream's
`GeoJsonFileLoader`. Eight notices live here, including `invalid_geometry`: it reports
JTS's own validation-error wording, so the message table is generated from the pinned jar
(`tools/generate_jts_messages.py`) and the geometry engine lives in `geometry/`.

`invalid_geometry` can only ever name a **Polygon**. A MultiPolygon is four levels of
array deep, `validateCoordinates` indexes three, and the throw is swallowed per feature,
so upstream's MultiPolygon branch is unreachable. See DroppedFeature.

Two measured behaviours shape the control flow and are easy to get backwards:

- A missing or wrong root `type`, malformed JSON, or any unparsable feature makes
  the file `UNPARSABLE_ROWS`, so it holds no rows. Every feature is still examined
  first and every feature's notices are still emitted: `hasUnparsableFeature`
  accumulates across the loop and is thrown after it.
- `validateCoordinates` runs before the geometry-type dispatch and assumes three
  levels of array nesting, so a `Point` or `LineString` makes upstream throw into a
  bare `catch (Exception)` that only logs. See divergence 6: the file is dropped
  with no notice and no system error, where we report a system error.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from gtfs_validator.geojson.constants import (
    FEATURE_COLLECTION_TYPE,
    FEATURES,
    FILENAME,
    ROOT_KEYS,
    DroppedFeature,
    DuplicateKey,
    UnparsableFeature,
    UnreadableGeoJson,
)
from gtfs_validator.geojson.decoding import _as_string, decode
from gtfs_validator.geojson.features import _check_feature, _missing, _notice, _unknown_keys
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.table_status import TableLoad, TableStatus

__all__ = ["DroppedFeature", "UnparsableFeature", "UnreadableGeoJson", "decode", "parse"]


def parse(text: str, notices: NoticeContainer, load: TableLoad | None = None) -> list[dict]:
    """Parse the file, emitting notices, and return the features that survived.

    An empty list with the load marked UNPARSABLE_ROWS is the "no rows" state every
    downstream rule already understands: plan 4 established that a table in that
    state must look empty to a file rule, and that cost a P1 to get right.
    """
    load = load if load is not None else TableLoad()
    try:
        root = decode(text)
    except DuplicateKey as duplicate:
        notices.add(
            _notice(
                "geo_json_duplicated_element",
                Severity.ERROR,
                {"filename": FILENAME, "duplicatedElement": duplicate.key},
            )
        )
        load.fail(TableStatus.UNPARSABLE_ROWS)
        return []
    except json.JSONDecodeError as error:
        # The message is our decoder's, not Gson's: see divergence 5.
        notices.add(
            _notice(
                "malformed_json",
                Severity.ERROR,
                {"filename": FILENAME, "message": str(error)},
            )
        )
        load.fail(TableStatus.UNPARSABLE_ROWS)
        return []

    if not isinstance(root, dict):
        notices.add(
            _notice(
                "malformed_json",
                Severity.ERROR,
                {"filename": FILENAME, "message": "Expected a JSON object at the root"},
            )
        )
        load.fail(TableStatus.UNPARSABLE_ROWS)
        return []

    for notice in _unknown_keys(root, ROOT_KEYS):
        notices.add(notice)

    if "type" not in root:
        notices.add(_missing(None, None, "type"))
        load.fail(TableStatus.UNPARSABLE_ROWS)
        return []
    root_type = _as_string(root["type"])
    if root_type != FEATURE_COLLECTION_TYPE:
        notices.add(
            _notice(
                "unsupported_geo_json_type",
                Severity.ERROR,
                {
                    "geoJsonType": root_type,
                    "message": (
                        f"Unsupported GeoJSON type: {root_type}. "
                        f"Use '{FEATURE_COLLECTION_TYPE}' instead."
                    ),
                },
            )
        )
        load.fail(TableStatus.UNPARSABLE_ROWS)
        return []

    # getAsJsonArray throws on a non-array and returns null when the key is absent,
    # and upstream's bare catch then drops the file. `or []` normalised null, false,
    # 0, "" and {} into a valid empty collection and left the load parsable.
    collection = root.get(FEATURES)
    if not isinstance(collection, list):
        raise UnreadableGeoJson(f"{FEATURES} is {type(collection).__name__}, expected an array")

    features: list[dict] = []
    unparsable = False
    for index, feature in enumerate(collection):
        try:
            for notice in _check_feature(feature, index):
                notices.add(notice)
        except UnparsableFeature:
            # Accumulated rather than raised here: upstream examines every feature
            # and emits every feature's notices, then throws after the loop.
            unparsable = True
            continue
        except DroppedFeature:
            # No notice and no effect on the file's status: the feature simply never
            # becomes a location, so a reference to it is a foreign key violation.
            continue
        features.append(
            {
                "feature_id": _as_string(feature["id"]),
                "feature_index": index,
                "geometry_type": _as_string(feature["geometry"]["type"]),
                # The rings, for the rule that compares two zones' geometry rather than their
                # ids. Re-serialised rather than kept as an object because the store binds
                # columns, and a ring list is not one.
                "coordinates": json.dumps(feature["geometry"]["coordinates"]),
            }
        )
    if unparsable:
        load.fail(TableStatus.UNPARSABLE_ROWS)
        return []
    for notice in _duplicate_keys(features):
        notices.add(notice)
    return features


def _duplicate_keys(features: list[dict]) -> Iterator[Notice]:
    """One notice per feature id already seen, keyed first-wins.

    `GtfsGeoJsonFeaturesContainer.setupIndices` upstream, which runs while the container builds its
    id map rather than from any validator, which is why this is not a rule module.

    **After the unparsable check on purpose.** One feature missing a required element makes the whole
    file unparsable, and upstream then builds the container with the constructor that indexes
    nothing, so a feed carrying both a broken feature and a duplicate pair draws no duplicate notice
    at all. Measured on `dgk5`. Emitting from inside the loop above would report on a feed the jar
    passes.

    First-wins rather than last-wins: the map is never overwritten, so a third occurrence reports
    against the first one's index and not the previous one's. Measured on `dgk2`.

    Upstream guards with `hasFeatureId()`, a null test blind to the empty string. That branch is
    unreachable: an empty `id` draws missing_required_element and the feature never becomes an
    entity, so having reached this list is the same condition. Measured on `dgk4`.
    """
    first: dict[str, int] = {}
    for feature in features:
        identifier = feature["feature_id"]
        if identifier not in first:
            first[identifier] = feature["feature_index"]
            continue
        yield _notice(
            "duplicate_geo_json_key",
            Severity.ERROR,
            {
                "featureId": identifier,
                "firstIndex": first[identifier],
                "secondIndex": feature["feature_index"],
            },
        )
