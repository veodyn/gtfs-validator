"""ShapeToStopMatchingValidator's walk: which trips it visits, and what state it carries.

The four codes come out of one pass, and the pass carries two pieces of state that decide whether a
notice exists at all: a set of trip fingerprints that collapses identical trips, and a set of
reported stop ids that suppresses a repeated too-far notice across every trip on the shape and
across both distance passes. Neither is visible in a single notice's fields, which is why they are
tested here rather than in `test_rules_stop_to_shape`.

The gates are here too. Four tables must be non-empty, and that is a different question from
whether they loaded: an empty table that parsed correctly still stops the validator.
"""

from __future__ import annotations

from shapematchfeed import (
    FAR_SHAPE,
    FAR_STOPS,
    OUT_OF_ORDER,
    TOO_FAR,
    all_codes,
    feed,
    fire,
    route,
    shape,
    stop_times,
    stops,
    trip,
)

# Three stops whose positions run *backwards* along FAR_SHAPE, so any trip visiting S1 before
# another of them draws one `stops_match_shape_out_of_order` notice. That code is one per trip and
# is not deduplicated by stop, which is what makes it able to count trips.
REVERSED_STOPS = (
    ("S1", "East", 40.0, -73.99),
    ("S2", "West", 40.0, -74.0),
    ("S3", "Middle", 40.0, -73.995),
)


def _reversed_feed(trips_rows, times_rows):
    return feed(
        stops_rows=stops(*REVERSED_STOPS),
        trips_rows=trips_rows,
        times_rows=times_rows,
        shape_rows=shape(*FAR_SHAPE),
    )


def test_a_shape_no_trip_references_is_not_matched():
    """`tripTable.byShapeId` returning empty is upstream's `continue`.

    So a feed whose shapes are all orphaned costs nothing, which is what keeps the geometry off
    the critical path for the common case of a feed carrying unused shapes.
    """
    view = feed(
        stops_rows=stops(*FAR_STOPS),
        trips_rows=[trip(shape_id="OTHER")],
        times_rows=stop_times("T1", "S1", "S2", "S3"),
        shape_rows=shape(*FAR_SHAPE),
    )
    assert all_codes(view) == []


def test_a_trip_with_no_shape_id_is_matched_against_a_shape_whose_id_is_empty():
    """`shapeId()` on an unset field is "", and the container indexes on that.

    So a feed whose `trips.txt` has no `shape_id` column at all still has its trip matched, against
    a shape whose own id is the empty string. Measured on `quoted_whitespace_shape_id.zip`, where
    the shape id is a quoted whitespace cell the loader stores as "": the jar reports
    `stop_too_far_from_shape` and a lookup keyed on the stored value alone found no trips and
    reported nothing.

    The reported `shapeId` is "" rather than null for the same reason.
    """
    trip_without_shape = {"_row_number": 2, "trip_id": "T1", "route_id": "R1"}
    view = feed(
        stops_rows=stops(*FAR_STOPS),
        trips_rows=[trip_without_shape],
        times_rows=stop_times("T1", "S1", "S2", "S3"),
        shape_rows=[
            {
                "_row_number": 2 + index,
                "shape_id": "",
                "shape_pt_lat": point[0],
                "shape_pt_lon": point[1],
                "shape_pt_sequence": index + 1,
            }
            for index, point in enumerate(FAR_SHAPE)
        ],
    )
    reported = fire(TOO_FAR, view)
    assert [(row["shapeId"], row["stopId"]) for row in reported] == [("", "S2")]


def test_a_trip_naming_a_missing_route_is_skipped():
    """A broken route reference is another rule's notice, and this validator goes quiet.

    Not silently harmless: the route decides the large-station multiplier, so continuing without
    one would have to invent a threshold.
    """
    view = feed(
        stops_rows=stops(*FAR_STOPS),
        trips_rows=[trip(route_id="MISSING")],
        times_rows=stop_times("T1", "S1", "S2", "S3"),
        shape_rows=shape(*FAR_SHAPE),
        routes_rows=[route()],
    )
    assert all_codes(view) == []


def test_a_second_trip_with_the_same_stop_pattern_is_not_matched_twice():
    """The trip fingerprint collapses identical trips, so only the first is reported.

    **Asserted on the out-of-order code, not the too-far one, and that is the point.** These three
    fingerprint tests were first written against `stop_too_far_from_shape`, and a review showed
    they passed with the fingerprint replaced by a unique value per call: `reported_stop_ids`
    suppresses the second trip's repeat of the same far stop, so a collapsed fingerprint and a
    suppressed duplicate produce the same notice list. `stops_match_shape_out_of_order` is one per
    trip and is not deduplicated by stop, so it counts trips rather than stops.

    Both mutations were run against the rewritten tests: a constant fingerprint and a unique one
    each fail at least one of the three.
    """
    view = _reversed_feed(
        [trip("T1", number=2), trip("T2", number=3)],
        stop_times("T1", "S1", "S2") + stop_times("T2", "S1", "S2", start_row=4),
    )
    assert [row["tripCsvRowNumber"] for row in fire(OUT_OF_ORDER, view)] == [2]


def test_a_second_trip_with_a_different_pattern_is_matched():
    """The other half of the fingerprint: a different stop list is a different trip.

    Two notices, one per trip. A fingerprint that collapsed everything would report one.
    """
    view = _reversed_feed(
        [trip("T1", number=2), trip("T2", number=3)],
        stop_times("T1", "S1", "S2") + stop_times("T2", "S1", "S3", start_row=4),
    )
    assert [row["tripCsvRowNumber"] for row in fire(OUT_OF_ORDER, view)] == [2, 3]


def test_a_differing_shape_dist_traveled_makes_two_trips_distinct():
    """The fingerprint hashes the distances as well as the ids, eight bytes each.

    Two trips calling at the same stops in the same order, differing only in one
    `shape_dist_traveled`, are two trips to upstream. Hashing the ids alone would collapse them
    into one notice, so this is the test that `put_double` is in the fingerprint at all.
    """
    view = _reversed_feed(
        [trip("T1", number=2), trip("T2", number=3)],
        stop_times("T1", ("S1", 10), ("S2", 20))
        + stop_times("T2", ("S1", 10), ("S2", 30), start_row=4),
    )
    assert [row["tripCsvRowNumber"] for row in fire(OUT_OF_ORDER, view)] == [2, 3]


def test_the_same_stop_is_reported_once_across_trips():
    """`reported_stop_ids` spans the shape, not the trip: two trips, one notice for S2."""
    view = feed(
        stops_rows=stops(
            ("S1", "First", 40.0, -74.0),
            ("S2", "Far", 40.003, -73.995),
            ("S3", "Last", 40.0, -73.99),
        ),
        trips_rows=[trip("T1", number=2), trip("T2", number=3)],
        times_rows=stop_times("T1", "S1", "S2", "S3")
        + stop_times("T2", "S2", "S1", "S3", start_row=5),
        shape_rows=shape(*FAR_SHAPE),
    )
    assert [row["stopId"] for row in fire(TOO_FAR, view)] == ["S2"]


def test_the_same_stop_is_reported_again_for_a_second_shape():
    """Both sets are reset per shape, so a stop far from two shapes draws two notices.

    The placement of that reset is upstream's and is the difference between per-shape and
    per-feed deduplication.

    **SH2 comes first**, and that is measured rather than chosen: shapes are walked in
    `Multimaps.asMap(byShapeIdMap())` order, which is Guava's bucket order and not file order. The
    jar reports this feed as SH2 then SH1, and this test first asserted the other way round
    because file order is the intuitive guess.
    """
    view = feed(
        stops_rows=stops(*FAR_STOPS),
        trips_rows=[trip("T1", shape_id="SH1", number=2), trip("T2", shape_id="SH2", number=3)],
        times_rows=stop_times("T1", "S1", "S2", "S3")
        + stop_times("T2", "S1", "S2", "S3", start_row=5),
        shape_rows=shape(*FAR_SHAPE) + shape(*FAR_SHAPE, shape_id="SH2", start_row=5),
    )
    assert [(row["shapeId"], row["stopId"]) for row in fire(TOO_FAR, view)] == [
        ("SH2", "S2"),
        ("SH1", "S2"),
    ]


def test_a_stop_time_with_no_stop_id_is_skipped():
    """`stopId().isEmpty()`, which covers a blank cell and a missing column alike.

    The stop still became a point at latitude 0, longitude 0, so it is a stop the matcher failed
    to place; the notice is dropped at reporting time rather than the stop being dropped from the
    sequence. The difference shows in which stops count as first and last, and in this feed it is
    the reason S1 and S3 are still matched.
    """
    times = stop_times("T1", "S1", "S2", "S3")
    times[1]["stop_id"] = ""
    view = feed(
        stops_rows=stops(*FAR_STOPS),
        trips_rows=[trip()],
        times_rows=times,
        shape_rows=shape(*FAR_SHAPE),
    )
    assert fire(TOO_FAR, view) == []


def test_an_empty_stops_table_stops_the_validator():
    """All four tables must hold something, and an empty one that loaded is still empty.

    Not a dependency gate: these tables parsed correctly. Upstream returns before matching, and a
    port that read "no stops" as "nothing to check" would agree by accident here and disagree the
    moment another table is the empty one.
    """
    view = feed(
        stops_rows=[],
        trips_rows=[trip()],
        times_rows=stop_times("T1", "S1", "S2", "S3"),
        shape_rows=shape(*FAR_SHAPE),
    )
    assert all_codes(view) == []


def test_an_empty_stop_times_table_stops_the_validator():
    view = feed(
        stops_rows=stops(*FAR_STOPS),
        trips_rows=[trip()],
        times_rows=[],
        shape_rows=shape(*FAR_SHAPE),
    )
    assert all_codes(view) == []


def test_an_empty_shapes_table_stops_the_validator():
    view = feed(
        stops_rows=stops(*FAR_STOPS),
        trips_rows=[trip()],
        times_rows=stop_times("T1", "S1", "S2", "S3"),
        shape_rows=[],
    )
    assert all_codes(view) == []


def test_an_empty_trips_table_stops_the_validator():
    """Reached through the per-shape lookup rather than through an emptiness test of its own.

    Upstream tests `tripTable.getEntities().isEmpty()` up front; here the same feed produces no
    trips for any shape, so the walk is empty either way. Worth pinning because the two routes to
    silence are different code.
    """
    view = feed(
        stops_rows=stops(*FAR_STOPS),
        trips_rows=[],
        times_rows=stop_times("T1", "S1", "S2", "S3"),
        shape_rows=shape(*FAR_SHAPE),
    )
    assert all_codes(view) == []
