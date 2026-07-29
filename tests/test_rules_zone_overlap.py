"""overlapping_zone_and_pickup_drop_off_window, measured on the `zone1` probe.

Eight trips, each isolating one branch of `OverlappingPickupDropOffZoneValidator`. The jar
reports three notices on that feed: from T1 (a proper zone overlap), T7 (types matching on
drop-off only) and T8 (three rows of which one pair overlaps).

Three separate gates have to fail for a pair to be reported, and the file is organised by them:
the types, the windows, and the zones. The zone gate is JTS's `overlaps`, which is not the
English word: containment is not overlap and a shared edge is not overlap. Those two are the
cases that make this rule quieter than a reading of its name suggests, and both are measured.
"""

from __future__ import annotations

import json

import pytest

from fakefeed import FakeFeed
from gtfs_validator.notices import Severity
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import DependencyFailed
from zoneoverlap import (
    CODE,
    COORDINATE_DRIVER,
    CTX,
    H8,
    H9,
    H10,
    H11,
    H12,
    PHONE_AGENCY,
    ZONES,
    fire,
    square,
    stop_time,
)


def test_an_overlapping_pair_names_every_field_the_jar_does():
    """zone1 T1: L1 and L2 properly overlap and the windows do too."""
    rows = [
        stop_time(2, "T1", 1, "L1", H8, H10),
        stop_time(3, "T1", 2, "L2", H9, H11),
    ]
    assert fire(rows) == [
        {
            "tripId": "T1",
            "stopSequence1": 1,
            "locationId1": "L1",
            "startPickupDropOffWindow1": "08:00:00",
            "endPickupDropOffWindow1": "10:00:00",
            "stopSequence2": 2,
            "locationId2": "L2",
            "startPickupDropOffWindow2": "09:00:00",
            "endPickupDropOffWindow2": "11:00:00",
        }
    ]


def test_a_zone_contained_in_the_other_does_not_overlap_it():
    """zone1 T2: L3 is wholly inside L1, and JTS `overlaps` is false for containment.

    The windows overlap and the types match, so the zone predicate is the only thing keeping
    the jar quiet. A rule testing "do these zones intersect" would report this pair.
    """
    rows = [
        stop_time(2, "T2", 1, "L1", H8, H10),
        stop_time(3, "T2", 2, "L3", H9, H11),
    ]
    assert fire(rows) == []


def test_zones_sharing_only_an_edge_do_not_overlap():
    """zone1 T3: L4 sits alongside L1 sharing one edge, so their interiors never meet."""
    rows = [
        stop_time(2, "T3", 1, "L1", H8, H10),
        stop_time(3, "T3", 2, "L4", H9, H11),
    ]
    assert fire(rows) == []


def test_identical_zones_do_not_overlap_either():
    """zone1 T4: L6 is L1 exactly, so neither has any area outside the other."""
    rows = [
        stop_time(2, "T4", 1, "L1", H8, H10),
        stop_time(3, "T4", 2, "L6", H9, H11),
    ]
    assert fire(rows) == []


def test_windows_that_only_touch_are_not_overlapping():
    """zone1 T5: the first window ends exactly when the second begins.

    Upstream tests that equality explicitly, on top of the after/before pair, so touching is
    excluded at both ends of the window rather than only at one.
    """
    rows = [
        stop_time(2, "T5", 1, "L1", H8, H9),
        stop_time(3, "T5", 2, "L2", H9, H11),
    ]
    assert fire(rows) == []


def test_a_pair_differing_in_both_types_is_skipped():
    """zone1 T6: pickup and drop-off are swapped, so neither matches."""
    rows = [
        stop_time(2, "T6", 1, "L1", H8, H10),
        stop_time(3, "T6", 2, "L2", H9, H11, pickup=PHONE_AGENCY, drop_off=COORDINATE_DRIVER),
        stop_time(4, "T6", 3, "L2", H9, H11, pickup=COORDINATE_DRIVER, drop_off=PHONE_AGENCY),
    ]
    assert [n["stopSequence2"] for n in fire(rows)] == [2]


def test_matching_on_one_type_alone_is_enough():
    """zone1 T7: the pickup types differ and the drop-off types agree, and the jar reports it.

    The condition is `pickup != pickup && dropOff != dropOff`, so it takes *both* differing to
    skip a pair. Reading it as "the types must match" would lose this notice.
    """
    rows = [
        stop_time(2, "T7", 1, "L1", H8, H10),
        stop_time(3, "T7", 2, "L2", H9, H11, pickup=COORDINATE_DRIVER, drop_off=COORDINATE_DRIVER),
    ]
    assert [(n["locationId1"], n["locationId2"]) for n in fire(rows)] == [("L1", "L2")]


def test_only_the_overlapping_pair_of_three_rows_is_reported():
    """zone1 T8: L1 and L2 overlap, L5 is far from both, so one notice from three rows."""
    rows = [
        stop_time(2, "T8", 1, "L1", H8, H12),
        stop_time(3, "T8", 2, "L2", H9, H12),
        stop_time(4, "T8", 3, "L5", H9 + 1800, H12),
    ]
    assert [(n["stopSequence1"], n["stopSequence2"]) for n in fire(rows)] == [(1, 2)]


def test_a_pair_naming_the_same_location_is_skipped():
    """Two rows on one zone are the same zone, and a zone does not overlap itself."""
    rows = [
        stop_time(2, "T9", 1, "L1", H8, H10),
        stop_time(3, "T9", 2, "L1", H9, H11),
    ]
    assert fire(rows) == []


def test_a_row_missing_a_window_or_a_location_is_skipped():
    """All four window fields and both location ids are required before anything is compared."""
    for missing in ("start_pickup_drop_off_window", "end_pickup_drop_off_window", "location_id"):
        rows = [
            stop_time(2, "TA", 1, "L1", H8, H10),
            stop_time(3, "TA", 2, "L2", H9, H11),
        ]
        rows[0][missing] = None
        assert fire(rows) == [], missing


def test_a_location_with_no_feature_is_skipped():
    """A stop time naming a zone the file does not declare is a foreign key notice elsewhere."""
    rows = [
        stop_time(2, "TB", 1, "L1", H8, H10),
        stop_time(3, "TB", 2, "LZ", H9, H11),
    ]
    assert fire(rows) == []


def test_both_types_absent_default_to_regular_and_match():
    """zone2 V1: both rows leave pickup_type and drop_off_type blank, and the jar reports.

    An unset enum is the type's zero, which is REGULAR, so the two rows match on both fields.
    This rule first read an absent value as UNRECOGNIZED and skipped the pair, which is the
    opposite answer: absent is a default, unparsable is UNRECOGNIZED, and the store already tells
    them apart by holding None for the first and -1 for the second.
    """
    rows = [
        stop_time(2, "V1", 1, "L1", H8, H10, pickup=None, drop_off=None),
        stop_time(3, "V1", 2, "L2", H9, H11, pickup=None, drop_off=None),
    ]
    assert [(n["locationId1"], n["locationId2"]) for n in fire(rows)] == [("L1", "L2")]


def test_an_unrecognised_type_skips_the_pair():
    """zone2 V2: both rows carry an out-of-range number, which the store keeps as -1."""
    rows = [
        stop_time(2, "V2", 1, "L1", H8, H10, pickup=-1, drop_off=-1),
        stop_time(3, "V2", 2, "L2", H9, H11, pickup=-1, drop_off=-1),
    ]
    assert fire(rows) == []


def test_a_zone_whose_geometry_type_is_unsupported_has_no_geometry():
    """zone2 V3: a feature typed "Hexagon" reaches the container with a null geometry.

    Upstream builds the JTS geometry inside the type dispatch, so a type it does not support
    leaves `geometryDefinition` null and `geometryOverlaps` answers false. The ring is a perfectly
    good overlapping square, so treating the feature as a polygon reports a pair the jar does not.
    """
    zones = [
        {**ZONES[0], "feature_id": "H1", "geometry_type": "Hexagon"},
        ZONES[1],
    ]
    rows = [
        stop_time(2, "V3", 1, "H1", H8, H10),
        stop_time(3, "V3", 2, "L2", H9, H11),
    ]
    assert fire(rows, zones=zones) == []


def test_the_first_feature_wins_a_duplicated_id():
    """zone2 V4: `D1` is declared twice, and the container keeps the first.

    The first `D1` overlaps L2 and the second is twenty degrees away, so last-wins reports
    nothing and first-wins reports the pair. The jar reports the pair.
    """
    zones = [
        {**ZONES[0], "feature_id": "D1"},
        {**ZONES[1]},
        {
            "_row_number": 9,
            "feature_index": 9,
            "feature_id": "D1",
            "geometry_type": "Polygon",
            "coordinates": json.dumps(square(20.0, 20.0, 1.0)),
        },
    ]
    rows = [
        stop_time(2, "V4", 1, "D1", H8, H10),
        stop_time(3, "V4", 2, "L2", H9, H11),
    ]
    assert [(n["locationId1"], n["locationId2"]) for n in fire(rows, zones=zones)] == [("D1", "L2")]


def test_a_three_dimensional_position_keeps_its_first_two_ordinates():
    """zone2 V5: a ring whose positions carry an altitude, which GeoJSON allows.

    Upstream reads index 0 and 1 and ignores the rest. Unpacking the position as a pair instead
    raised, and for a file rule that means the rule's whole output is discarded: a single 3D zone
    anywhere in the file would have cost every notice this code produces.
    """
    with_altitude = [[[*point, 5.0] for point in square(0.5, 0.5, 1.0)[0]]]
    zones = [
        ZONES[0],
        {
            "_row_number": 8,
            "feature_index": 8,
            "feature_id": "Z1",
            "geometry_type": "Polygon",
            "coordinates": json.dumps(with_altitude),
        },
    ]
    rows = [
        stop_time(2, "V5", 1, "Z1", H8, H10),
        stop_time(3, "V5", 2, "L1", H9, H11),
    ]
    assert [(n["locationId1"], n["locationId2"]) for n in fire(rows, zones=zones)] == [("Z1", "L1")]


def test_a_missing_geojson_file_stops_the_rule_before_any_comparison():
    """`isMissingFile()` on either container returns immediately.

    An ordinary scheduled feed has no locations.geojson, and without this the rule walked every
    trip and compared every pair of its stop times to look each one up in an empty index: 1.74
    million comparisons on the scale feed for an answer that was always no notice.
    """
    registry.load_rules()
    view = FakeFeed({"stop_times.txt": [stop_time(2, "T1", 1, "L1", H8, H10)]})
    assert list(registry.FILE_REGISTRY[CODE].func(view, CTX)) == []


def test_the_code_is_registered_as_an_error():
    registry.load_rules()
    assert registry.FILE_REGISTRY[CODE].severity is Severity.ERROR


@pytest.mark.parametrize("table", ["stop_times.txt", "locations.geojson"])
def test_either_injected_table_failing_silences_the_rule(table):
    rows = [
        stop_time(2, "T1", 1, "L1", H8, H10),
        stop_time(3, "T1", 2, "L2", H9, H11),
    ]
    with pytest.raises(DependencyFailed):
        fire(rows, unindexable=frozenset({table}))
