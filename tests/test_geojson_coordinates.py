"""`validateCoordinates`: the point-level scan that runs before the geometry-type check.

Split from `test_geojson.py`, which covers the structural notices, when the two together passed
the file-size limit. The division is upstream's own: this scan walks every coordinate of every
feature and *then* the geometry type is dispatched on, so a ring's suspicious points are reported
before anything decides whether the geometry is one this validator supports.

That ordering is only visible for a geometry whose coordinates are nested to a ring's depth. A
`Point` is two levels shallower, so the scan throws while indexing rather than reporting anything,
and the file is dropped with no point notice at all; the earlier wording here said a Point is
scanned first, which is the one case where it is not.
"""

from geojsonfeed import collection, contexts, feature, run


def ring_at(*points):
    """A single ring through the given points, closed by repeating the first."""
    return [[list(point) for point in (*points, points[0])]]


def test_a_ring_near_the_origin_reports_every_point():
    """Measured on the jar: one notice per coordinate *pair*, not per distinct place.

    A ring repeats its first point as its last, and upstream reports that point twice: a
    four-point ring near the origin draws four notices whose first and last are identical.
    """
    text = collection(
        feature(
            geometry={"type": "Polygon", "coordinates": ring_at((0.5, 0.5), (0.6, 0.5), (0.6, 0.6))}
        )
    )
    _, found, _ = run(text)
    got = contexts(found, "point_near_origin")
    assert got == [
        {
            "filename": "locations.geojson",
            "featureIndex": 0,
            "entityId": "L1",
            "latFieldValue": 0.5,
            "lonFieldValue": 0.5,
        },
        {
            "filename": "locations.geojson",
            "featureIndex": 0,
            "entityId": "L1",
            "latFieldValue": 0.5,
            "lonFieldValue": 0.6,
        },
        {
            "filename": "locations.geojson",
            "featureIndex": 0,
            "entityId": "L1",
            "latFieldValue": 0.6,
            "lonFieldValue": 0.6,
        },
        {
            "filename": "locations.geojson",
            "featureIndex": 0,
            "entityId": "L1",
            "latFieldValue": 0.5,
            "lonFieldValue": 0.5,
        },
    ]


def test_both_bounds_are_inclusive():
    """Measured: exactly (1.0, 1.0) is near the origin and exactly 89 degrees is near a pole.

    Upstream writes `<= 1` and `>= 89`, so a fixture one step outside either bound has to be
    strictly outside it. Both signs of latitude count for the pole.
    """
    origin = collection(
        feature(
            geometry={
                "type": "Polygon",
                "coordinates": ring_at((1.0, 1.0), (-1.0, 1.0), (0.0, -1.0)),
            }
        )
    )
    _, found, _ = run(origin)
    assert len(contexts(found, "point_near_origin")) == 4

    pole = collection(
        feature(
            geometry={
                "type": "Polygon",
                "coordinates": ring_at((20.0, 89.0), (21.0, -89.0), (22.0, 88.9)),
            }
        )
    )
    _, found, _ = run(pole)
    assert [row["latFieldValue"] for row in contexts(found, "point_near_pole")] == [
        89.0,
        -89.0,
        89.0,
    ]


def test_the_origin_test_wins_over_the_pole_test():
    """The two are chained with `else if`, so a point cannot draw both. Unreachable in
    practice, since no point is within a degree of the origin and 89 of a pole, but the chain
    is what upstream wrote and the code reads the same way."""
    text = collection(
        feature(
            geometry={"type": "Polygon", "coordinates": ring_at((0.5, 0.5), (0.6, 0.5), (0.6, 0.6))}
        )
    )
    _, found, _ = run(text)
    assert contexts(found, "point_near_pole") == []


def test_the_coordinate_scan_runs_before_the_geometry_type_check():
    """Measured on the jar: a LineString whose coordinates are polygon-shaped and near a pole
    draws both the pole notices *and* unsupported_geometry_type.

    Upstream calls validateCoordinates before dispatching on the geometry type, so the order
    of these two is observable rather than a detail.
    """
    text = collection(
        feature(geometry={"type": "LineString", "coordinates": [[[10.0, 89.5], [11.0, 89.5]]]})
    )
    _, found, _ = run(text)
    assert len(contexts(found, "point_near_pole")) == 2
    assert contexts(found, "unsupported_geometry_type") == [
        {"featureIndex": 0, "featureId": "L1", "geometryType": "LineString"}
    ]


def test_a_feature_missing_its_id_is_never_scanned():
    """Measured: a feature with no id near the origin draws missing_required_element and no
    point_near_origin. Upstream validates the geometry only when every required field is
    present, so the missing-field guard comes first."""
    text = collection(
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": ring_at((0.5, 0.5), (0.6, 0.5), (0.6, 0.6)),
            },
        }
    )
    _, found, _ = run(text)
    assert contexts(found, "missing_required_element") == [
        {"featureIndex": 0, "missingElement": "features.id"}
    ]
    assert contexts(found, "point_near_origin") == []
