"""ShapeIncreasingDistanceValidator: the four codes one pass over each shape produces.

Every expectation was measured on `shapedist.zip`, a probe carrying one shape per branch: a
decreasing pair, an equal pair at identical coordinates, an equal pair 111 m apart, an equal pair
0.56 m apart, a shape with a gap in `shape_dist_traveled`, and a shape whose rows are out of
sequence order in the file.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")


def point(row, shape_id, sequence, distance, lat=40.0, lon=-73.0):
    return {
        "_row_number": row,
        "shape_id": shape_id,
        "shape_pt_sequence": sequence,
        "shape_dist_traveled": distance,
        "shape_pt_lat": lat,
        "shape_pt_lon": lon,
    }


def fire(code, points):
    registry.load_rules()
    feed = FakeFeed({"shapes.txt": points})
    return [notice.context for notice in registry.FILE_REGISTRY[code].func(feed, CTX)]


def test_a_decreasing_distance_reports_the_pair_inverted():
    """Measured on SH1, rows 2 to 4: the decrease is between row 3 (111.2) and row 4 (50.0),
    and the jar reports `csvRowNumber` 3 with `prevCsvRowNumber` 4.

    The fields are the wrong way round, and deliberately so: upstream calls
    `new DecreasingShapeDistanceNotice(prev, curr)` against a constructor declared
    `(GtfsShape current, GtfsShape previous)`, so the arguments are swapped. The other three
    codes in this validator take `(previous, current)` and are not affected. Naming the later
    row as `prev` looks like a defect on this side until the jar is asked.
    """
    points = [
        point(2, "SH1", 1, 0.0),
        point(3, "SH1", 2, 111.2),
        point(4, "SH1", 3, 50.0),
    ]
    assert fire("decreasing_shape_distance", points) == [
        {
            "shapeId": "SH1",
            "csvRowNumber": 3,
            "shapeDistTraveled": 111.2,
            "shapePtSequence": 2,
            "prevCsvRowNumber": 4,
            "prevShapeDistTraveled": 50.0,
            "prevShapePtSequence": 3,
        }
    ]


def test_pairs_are_taken_in_sequence_order_not_file_order():
    """Measured on SH6, whose rows are sequence 3, 1, 2 in that file order.

    Sorted by sequence the decrease is between row 19 (sequence 2, 111.2) and row 17
    (sequence 3, 50.0), and the jar reports exactly that pair. Walking the file order instead
    finds a decrease between the first two rows, which the jar does not report.
    """
    points = [
        point(17, "SH6", 3, 50.0),
        point(18, "SH6", 1, 0.0),
        point(19, "SH6", 2, 111.2),
    ]
    assert fire("decreasing_shape_distance", points) == [
        {
            "shapeId": "SH6",
            "csvRowNumber": 19,
            "shapeDistTraveled": 111.2,
            "shapePtSequence": 2,
            "prevCsvRowNumber": 17,
            "prevShapeDistTraveled": 50.0,
            "prevShapePtSequence": 3,
        }
    ]


def test_an_equal_distance_at_the_same_coordinates_is_a_duplicate_point():
    """Measured on SH2, rows 6 and 7. These fields are *not* inverted: `csvRowNumber` is the
    later row, which is the opposite of `decreasing_shape_distance` on the same validator."""
    points = [
        point(5, "SH2", 1, 0.0, 41.0),
        point(6, "SH2", 2, 111.2, 41.001),
        point(7, "SH2", 3, 111.2, 41.001),
    ]
    assert fire("equal_shape_distance_same_coordinates", points) == [
        {
            "shapeId": "SH2",
            "csvRowNumber": 7,
            "shapeDistTraveled": 111.2,
            "shapePtSequence": 3,
            "prevCsvRowNumber": 6,
            "prevShapeDistTraveled": 111.2,
            "prevShapePtSequence": 2,
        }
    ]


def test_an_equal_distance_far_apart_carries_the_measured_distance():
    """Measured on SH3: 42.001 to 42.002 at one longitude is 111.1951011779014 m.

    The value is `S2Earth.getDistanceMeters`, and this digit-for-digit expectation comes from
    the jar. See divergence 12 for the 0.8% of coordinate pairs where the final digit cannot
    be matched at all.
    """
    points = [
        point(8, "SH3", 1, 0.0, 42.0),
        point(9, "SH3", 2, 111.2, 42.001),
        point(10, "SH3", 3, 111.2, 42.002),
    ]
    assert fire("equal_shape_distance_diff_coordinates", points) == [
        {
            "shapeId": "SH3",
            "csvRowNumber": 10,
            "shapeDistTraveled": 111.2,
            "shapePtSequence": 3,
            "prevCsvRowNumber": 9,
            "prevShapeDistTraveled": 111.2,
            "prevShapePtSequence": 2,
            "actualDistanceBetweenShapePoints": 111.1951011779014,
        }
    ]


def test_an_equal_distance_just_under_the_threshold_is_only_a_warning():
    """Measured on SH4: 43.001 to 43.001005 is 0.5559755059637761 m, under the 1.11 m split.

    The threshold is not a round number and it is not in metres of latitude: 0.00001 degrees is
    1.1119510126348764 m, so a fixture meant to sit either side of 1.11 has to be measured.
    """
    points = [
        point(11, "SH4", 1, 0.0, 43.0),
        point(12, "SH4", 2, 111.2, 43.001),
        point(13, "SH4", 3, 111.2, 43.001005),
    ]
    assert fire("equal_shape_distance_diff_coordinates_distance_below_threshold", points) == [
        {
            "shapeId": "SH4",
            "csvRowNumber": 13,
            "shapeDistTraveled": 111.2,
            "shapePtSequence": 3,
            "prevCsvRowNumber": 12,
            "prevShapeDistTraveled": 111.2,
            "prevShapePtSequence": 2,
            "actualDistanceBetweenShapePoints": 0.5559755059637761,
        }
    ]


def test_the_threshold_is_closed_at_1_11_and_open_at_zero():
    """`>= 1.11` draws the error and `> 0` the warning, so a pair exactly 1.11 m apart is an
    error and a pair 0 m apart is neither: an identical-coordinate pair falls to the
    same-coordinates code instead. Both branches are upstream's own comparisons."""
    from gtfs_validator.s2earth import distance_meters

    # 0.00001 degrees of latitude is just over the threshold, measured.
    assert distance_meters(40.0, -73.0, 40.00001, -73.0) >= 1.11
    far = [point(2, "S", 1, 5.0, 40.0), point(3, "S", 2, 5.0, 40.00001)]
    assert len(fire("equal_shape_distance_diff_coordinates", far)) == 1
    assert fire("equal_shape_distance_diff_coordinates_distance_below_threshold", far) == []


@pytest.mark.parametrize(
    "code",
    [
        "decreasing_shape_distance",
        "equal_shape_distance_same_coordinates",
        "equal_shape_distance_diff_coordinates",
        "equal_shape_distance_diff_coordinates_distance_below_threshold",
    ],
)
def test_a_pair_missing_either_distance_is_skipped(code):
    """Measured on SH5, whose middle row leaves `shape_dist_traveled` blank: the jar reports
    nothing for it, not even for the outer pair whose values do decrease. Upstream requires
    `hasShapeDistTraveled()` on *both* points of a consecutive pair, and consecutive means
    adjacent in sequence, so a gap suppresses the two pairs it takes part in rather than
    joining the rows either side of it."""
    points = [
        point(14, "SH5", 1, 222.4, 44.0),
        point(15, "SH5", 2, None, 44.001),
        point(16, "SH5", 3, 0.0, 44.002),
    ]
    assert fire(code, points) == []


@pytest.mark.parametrize(
    "code",
    [
        "decreasing_shape_distance",
        "equal_shape_distance_same_coordinates",
        "equal_shape_distance_diff_coordinates",
        "equal_shape_distance_diff_coordinates_distance_below_threshold",
    ],
)
def test_a_properly_increasing_shape_draws_nothing(code):
    """The negative fixture for all four: strictly increasing distances at distinct points."""
    points = [
        point(2, "SH0", 1, 0.0, 40.000),
        point(3, "SH0", 2, 111.2, 40.001),
        point(4, "SH0", 3, 222.4, 40.002),
    ]
    assert fire(code, points) == []


def test_a_shape_of_one_point_has_no_pairs():
    """The walk starts at the second point, so a single-point shape is silent here. That shape
    is `single_shape_point`'s business, and these four say nothing about it."""
    assert fire("decreasing_shape_distance", [point(2, "SH7", 1, 0.0)]) == []


def test_shapes_come_out_in_hashmap_order():
    """Measured above the sample cap on a 1,005-shape feed: the jar's 1,000 samples begin
    SD0336, SD0578, SD0335 and match `hashmap_order` over the shape ids for all 1,000.

    Upstream iterates `Multimaps.asMap(table.byShapeIdMap()).values()`, and a Guava multimap
    over these keys comes out in HashMap order. Above the cap that decides which notices the
    report keeps, so it is part of the contract rather than an implementation detail.
    """
    ids = [f"SD{index:04d}" for index in range(1005)]
    points = []
    for index, shape_id in enumerate(ids):
        points.append(point(2 + index * 2, shape_id, 1, 100.0, 40.0 + index / 1e6))
        points.append(point(3 + index * 2, shape_id, 2, 50.0, 40.0 + index / 1e6, -73.001))
    reported = [row["shapeId"] for row in fire("decreasing_shape_distance", points)]
    assert len(reported) == 1005
    assert reported[:3] == ["SD0336", "SD0578", "SD0335"]


def test_few_shapes_above_the_cap_use_the_multimap_order():
    """The ordering case a thousand-key probe structurally cannot see.

    Measured on `shapecap`: five shapes whose ids separate a 16-bucket table from a 32-bucket
    one, each with 300 decreasing pairs, so the code reports 1,500 notices and keeps 1,000. The
    jar's samples cover S6, S7, S8 and S9. Upstream indexes with `ArrayListMultimap.create()`,
    pre-sized for 12 keys and so starting at 32 buckets, where `hashmap_order` starts at 16 and
    would have kept S10 in place of S9.

    Every earlier ordering probe in this project used about a thousand keys, by which point both
    collections have resized to a common capacity and agree exactly. That is why this survived an
    ordering audit: the probes could not distinguish the two.
    """
    ids = ["S6", "S7", "S8", "S9", "S10"]
    points = []
    row = 2
    for shape_id in ids:
        for sequence in range(1, 302):
            points.append(point(row, shape_id, sequence, 1000 - sequence, 40.0 + sequence / 1e6))
            row += 1
    reported = fire("decreasing_shape_distance", points)
    assert len(reported) == 1500
    kept = []
    for notice in reported[:1000]:
        if notice["shapeId"] not in kept:
            kept.append(notice["shapeId"])
    assert kept == ["S6", "S7", "S8", "S9"]
