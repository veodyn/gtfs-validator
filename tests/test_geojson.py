"""The locations.geojson parser, asserted against measured jar output.

Every expected context in this file came from running the jar on a feed carrying
that exact locations.geojson. The measurements are tabulated in the plan 6
implementation notes.
"""


import json

import pytest

from geojsonfeed import RING, collection, contexts, feature, run
from gtfs_validator.geojson import UnreadableGeoJson, parse
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.table_status import TableLoad, TableStatus


def test_a_valid_collection_draws_nothing():
    """The kept fields are the id, the index, the geometry type and the rings.

    The rings are here because `overlapping_zone_and_pickup_drop_off_window` compares two zones'
    geometry rather than their ids, and they are kept as the JSON text the store binds. This
    assertion is on the whole dict on purpose: what the parser keeps is a contract with every
    rule that reads a feature, so a field appearing or vanishing should fail here.
    """
    rows, found, load = run(collection(feature()))
    assert found == []
    assert load.status is TableStatus.PARSABLE_HEADERS_AND_ROWS
    assert rows == [
        {
            "feature_id": "L1",
            "feature_index": 0,
            "geometry_type": "Polygon",
            "coordinates": (
                "[[[-73.0, 40.0], [-73.0, 40.1], [-72.9, 40.1], [-72.9, 40.0], [-73.0, 40.0]]]"
            ),
        }
    ]


def test_truncated_json_is_malformed_and_holds_no_rows():
    rows, found, load = run('{"type": "FeatureCollection", "features": [')
    assert [n.code for n in found] == ["malformed_json"]
    assert contexts(found, "malformed_json")[0]["filename"] == "locations.geojson"
    assert rows == []
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_a_non_object_root_is_malformed():
    _, found, load = run("[1, 2, 3]")
    assert contexts(found, "malformed_json") == [
        {"filename": "locations.geojson", "message": "Expected a JSON object at the root"}
    ]
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_a_duplicate_key_is_reported_and_stops_parsing():
    # json.loads keeps the last value and the fact is gone, so object_pairs_hook is
    # the only place a duplicate is visible.
    _, found, load = run('{"type":"FeatureCollection","type":"FeatureCollection","features":[]}')
    assert contexts(found, "geo_json_duplicated_element") == [
        {"filename": "locations.geojson", "duplicatedElement": "type"}
    ]
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_a_missing_root_type_omits_the_index_and_id():
    # Upstream passes null for both and gson drops them, so the sample carries one
    # key. Measured.
    _, found, load = run(json.dumps({"features": [feature()]}))
    assert contexts(found, "missing_required_element") == [{"missingElement": "type"}]
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_a_wrong_root_type_names_itself_in_the_message():
    _, found, load = run(json.dumps({"type": "Feature", "features": []}))
    assert contexts(found, "unsupported_geo_json_type") == [
        {
            "geoJsonType": "Feature",
            "message": "Unsupported GeoJSON type: Feature. Use 'FeatureCollection' instead.",
        }
    ]
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_an_unknown_root_key_is_info_and_does_not_stop_parsing():
    rows, found, _ = run(collection(feature(), extra=1))
    assert contexts(found, "geo_json_unknown_element") == [
        {"filename": "locations.geojson", "unknownElement": "extra"}
    ]
    assert len(rows) == 1


def test_an_empty_feature_reports_four_missing_elements():
    # missingRequiredFields is a list and every absent field is added before
    # anything is emitted. Measured: four notices, and no featureId key on any.
    rows, found, load = run(collection({}))
    assert contexts(found, "missing_required_element") == [
        {"featureIndex": 0, "missingElement": "features.id"},
        {"featureIndex": 0, "missingElement": "features.type"},
        {"featureIndex": 0, "missingElement": "features.properties"},
        {"featureIndex": 0, "missingElement": "features.geometry"},
    ]
    assert rows == []
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_a_blank_id_is_reported_as_an_empty_string():
    # Assigned before the emptiness test, so the key is present and empty, where a
    # missing id omits it. Two different states, both measured.
    _, found, _ = run(collection(feature(id="")))
    assert contexts(found, "missing_required_element") == [
        {"featureIndex": 0, "featureId": "", "missingElement": "features.id"}
    ]


def test_a_wrong_feature_type_carries_three_context_fields():
    # The generated manifest lists this code with no context fields and the jar
    # emits three. The jar wins.
    _, found, _ = run(collection(feature(type="Thing")))
    assert contexts(found, "unsupported_feature_type") == [
        {"featureIndex": 0, "featureId": "L1", "featureType": "Thing"}
    ]


def test_a_geometry_missing_coordinates_reports_a_dotted_path():
    _, found, load = run(collection(feature(geometry={"type": "Polygon"})))
    assert contexts(found, "missing_required_element") == [
        {
            "featureIndex": 0,
            "featureId": "L1",
            "missingElement": "features.geometry.coordinates",
        }
    ]
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_a_geometry_missing_type_reports_only_the_type():
    # The two geometry checks are chained with elif upstream, so a geometry missing
    # both reports one element rather than two.
    _, found, _ = run(collection(feature(geometry={})))
    assert contexts(found, "missing_required_element") == [
        {"featureIndex": 0, "featureId": "L1", "missingElement": "features.geometry.type"}
    ]


def test_an_unknown_geometry_key_is_reported():
    rows, found, _ = run(
        collection(feature(geometry={"type": "Polygon", "coordinates": RING, "crs": "x"}))
    )
    assert contexts(found, "geo_json_unknown_element") == [
        {"filename": "locations.geojson", "unknownElement": "crs"}
    ]
    assert len(rows) == 1


def test_a_non_polygon_geometry_with_ring_coordinates_is_unsupported():
    # Measured with MultiLineString and with a made-up "Hexagon", both drawing the
    # notice. It cannot be tested with a Point: upstream's validateCoordinates
    # throws first and the file is silently dropped, so the notice is unreachable.
    # See divergence 6.
    for geometry_type in ("MultiLineString", "Hexagon"):
        _, found, _ = run(
            collection(feature(geometry={"type": geometry_type, "coordinates": RING}))
        )
        assert contexts(found, "unsupported_geometry_type") == [
            {"featureIndex": 0, "featureId": "L1", "geometryType": geometry_type}
        ], geometry_type


def test_an_invalid_geometry_costs_the_whole_file():
    """`createPolygon` returns null for a bad ring and the loader answers `return null`.

    That sets hasUnparsableFeature, so the file holds no rows at all and every *other* feature is
    lost with it. Measured: a feed whose third zone is a self-intersecting bow-tie draws
    invalid_geometry from the jar and no overlapping_zone_and_pickup_drop_off_window for the two
    valid zones that plainly overlap. Keeping the feature reported that pair and diverged.
    """
    bow_tie = [[[0.0, 0.0], [4.0, 4.0], [0.0, 4.0], [4.0, 0.0], [0.0, 0.0]]]
    rows, found, load = run(
        collection(
            feature(),
            feature(id="BOW", geometry={"type": "Polygon", "coordinates": bow_tie}),
        )
    )
    assert [n["featureId"] for n in contexts(found, "invalid_geometry")] == ["BOW"]
    assert rows == []
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_a_point_geometry_raises_for_the_loader_to_report():
    # Upstream throws from validateCoordinates into a bare catch that only logs, so
    # it emits no notice and no system error. We emit no GeoJSON notice either, and
    # the failure propagates so the caller records a system error: that is what
    # divergence 6 promises, and until the exception was separated from the
    # per-feature one the entry described behaviour the code did not have.
    notices = NoticeContainer()
    load = TableLoad()
    with pytest.raises(UnreadableGeoJson):
        parse(
            collection(feature(geometry={"type": "Point", "coordinates": [0.0, 0.0]})),
            notices,
            load,
        )
    assert [n.code for group in notices.grouped().values() for n in group] == []


def test_a_boolean_type_is_rendered_the_way_gson_renders_it():
    # getAsString gives lowercase "true" where Python's str gives "True", and the
    # value reaches the report. Measured: the jar draws geoJsonType "true" and a
    # message containing "true".
    _, found, _ = run('{"type": true, "features": []}')
    assert contexts(found, "unsupported_geo_json_type") == [
        {
            "geoJsonType": "true",
            "message": "Unsupported GeoJSON type: true. Use 'FeatureCollection' instead.",
        }
    ]


def test_a_numeric_feature_id_renders_as_a_java_double():
    """A feature with id 7 is valid, and its id reaches the report as "7.0".

    This test previously asserted "7" and called it measured. It was not: the jar reported
    nothing at all for that feed, so there was no rendering to compare against. Asked properly,
    with a feed where a numeric id reaches a notice, the jar reports `featureId: "7.0"` for
    unsupported_geometry_type and `entityId: "7.0"` for point_near_origin, and 8.5 as "8.5".
    """
    rows, found, _ = run(collection(feature(id=7)))
    assert found == []
    assert rows[0]["feature_id"] == "7.0"


def test_a_duplicate_inside_a_feature_is_reported():
    # The likeliest real shape, and the one a depth-tracking hook silently missed:
    # a feature lives inside the features *array*, arrays get no object_pairs_hook,
    # so per-object metadata never reached the root. See divergence 7.
    _, found, load = run(
        '{"type":"FeatureCollection","features":[{"id":"L1","id":"L2","type":"Feature",'
        '"properties":{},"geometry":{"type":"Polygon","coordinates":'
        "[[[0,0],[0,1],[1,1],[0,0]]]}}]}"
    )
    assert contexts(found, "geo_json_duplicated_element") == [
        {"filename": "locations.geojson", "duplicatedElement": "id"}
    ]
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_a_nested_duplicate_reports_the_inner_key():
    # Divergence 7: the jar reports the outer "type" here and we report "x", because
    # the hook fires bottom-up. Reporting the notice with the inner key beats the
    # alternative, which was not reporting it at all for the case above.
    _, found, _ = run('{"type":"FeatureCollection","type":{"x":1,"x":2},"features":[]}')
    assert contexts(found, "geo_json_duplicated_element") == [
        {"filename": "locations.geojson", "duplicatedElement": "x"}
    ]


def test_a_nested_duplicate_is_still_reported_when_it_is_the_only_one():
    _, found, _ = run('{"type":"FeatureCollection","features":[],"extra":{"x":1,"x":2}}')
    assert contexts(found, "geo_json_duplicated_element") == [
        {"filename": "locations.geojson", "duplicatedElement": "x"}
    ]


def test_every_feature_is_examined_before_the_file_is_abandoned():
    # hasUnparsableFeature accumulates across the loop and is thrown after it, so a
    # later feature's notices are still emitted even though no rows survive.
    rows, found, load = run(collection({}, feature(type="Thing")))
    assert contexts(found, "unsupported_feature_type") == [
        {"featureIndex": 1, "featureId": "L1", "featureType": "Thing"}
    ]
    assert len(contexts(found, "missing_required_element")) == 4
    assert rows == []
    assert load.status is TableStatus.UNPARSABLE_ROWS
