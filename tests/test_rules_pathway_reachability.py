"""PathwayReachableLocationValidator: what the two traversals reach, and in which direction.

Every expectation was measured on a probe feed run through the jar, named in the test that uses it.
The probes are `reach/pr1` through `pr13` in the scratchpad.

Which locations are then in scope for a notice, and what the notice carries, is next door in
`test_rules_pathway_reachability_scope`. The split is by responsibility: this half is the graph
search, that half is the reporting.
"""

from __future__ import annotations

from reachfeed import (
    BASE_STOPS,
    ENTRANCE,
    GENERIC_NODE,
    P1_BOTH_WAYS,
    PLATFORM,
    STATION,
    fire,
    pathway,
    reported_ids,
    stop,
)


def test_a_platform_with_no_pathway_reports_both_directions_failing():
    """Measured on `pr1`: P2 has no incident pathway, so neither search reaches it."""
    reported = fire(BASE_STOPS, [P1_BOTH_WAYS])
    assert [(row["stopId"], row["hasEntrance"], row["hasExit"]) for row in reported] == [
        ("P2", False, False)
    ]


def test_a_one_way_pathway_in_gives_an_entrance_and_no_exit():
    """Measured on `pr2`: `hasEntrance` true, `hasExit` false."""
    reported = fire(BASE_STOPS, [P1_BOTH_WAYS, pathway(3, "EN", "P2")])
    assert [(row["stopId"], row["hasEntrance"], row["hasExit"]) for row in reported] == [
        ("P2", True, False)
    ]


def test_a_one_way_pathway_out_gives_an_exit_and_no_entrance():
    """Measured on `pr3`: the mirror image, which a search in one direction only would miss."""
    reported = fire(BASE_STOPS, [P1_BOTH_WAYS, pathway(3, "P2", "EN")])
    assert [(row["stopId"], row["hasEntrance"], row["hasExit"]) for row in reported] == [
        ("P2", False, True)
    ]


def test_a_bidirectional_pathway_is_silent():
    """Measured on `pr4`. The negative case for the whole rule."""
    assert fire(BASE_STOPS, [P1_BOTH_WAYS, pathway(3, "EN", "P2", bidirectional=1)]) == []


def test_a_bidirectional_pathway_written_platform_first_is_still_traversable_both_ways():
    """Measured on `pr10`: every pathway written platform-to-entrance, and the jar is silent.

    "Bidirectional" is about the pathway, not about which column its endpoints sit in, so the
    forward search has to follow such a row *backwards* out of the entrance. Every other probe
    writes its pathways entrance-first, where the forward search only ever needs the `from_stop_id`
    index, so none of them can see this: a mutation that dropped the bidirectional test from the
    reverse-direction loop passed all eighteen tests that existed before this one.
    """
    pathways = [
        pathway(2, "P1", "EN", bidirectional=1),
        pathway(3, "P2", "EN", bidirectional=1),
    ]
    assert fire(BASE_STOPS, pathways) == []


def test_reachability_is_transitive_rather_than_adjacent():
    """Measured on `pr7`: two hops through a generic node, and the jar is silent.

    A test of adjacency to an entrance rather than of reachability would report all three.
    """
    stops = [*BASE_STOPS, stop(6, "GN", "Node", GENERIC_NODE, "ST")]
    pathways = [
        pathway(2, "EN", "GN", bidirectional=1),
        pathway(3, "GN", "P1", bidirectional=1),
        pathway(4, "GN", "P2", bidirectional=1),
    ]
    assert fire(stops, pathways) == []


def test_the_traversal_is_seeded_with_every_entrance_in_the_feed():
    """Measured on `pr9`: a platform in one station, reached from another station's entrance.

    The jar reports P1, in the station that has the entrance, and stays silent about P2, in the
    station that has none. A traversal scoped per station reports exactly the opposite pair, which
    makes this the test that separates the two designs.
    """
    stops = [
        stop(2, "ST1", "One", STATION),
        stop(3, "EN1", "Entrance One", ENTRANCE, "ST1"),
        stop(4, "P1", "Platform One", PLATFORM, "ST1"),
        stop(5, "ST2", "Two", STATION),
        stop(6, "P2", "Platform Two", PLATFORM, "ST2"),
    ]
    assert reported_ids(stops, [pathway(2, "EN1", "P2", bidirectional=1)]) == ["P1"]


def test_a_pathway_naming_a_stop_that_does_not_exist_still_connects_nothing():
    """The id is enqueued rather than dropped, because a broken reference is another rule's notice.

    Reported here as P2 alone: the pathway to NOWHERE keeps nothing reachable, and the absent stop
    is not itself a location this rule can report.
    """
    assert reported_ids(BASE_STOPS, [P1_BOTH_WAYS, pathway(3, "EN", "NOWHERE")]) == ["P2"]


def test_the_traversal_bridges_through_a_stop_that_does_not_exist():
    """Measured on `pr16`: `EN` to `MISSING` to `P2`, and the jar is silent.

    The stronger half of the case above, and the one that distinguishes the two designs. Enqueueing
    an unknown id is not merely harmless: upstream reaches P2 *through* a stop no row defines, so
    dropping unknown ids would disconnect it and report. The test above cannot show that, because
    nothing lies beyond `NOWHERE`.
    """
    pathways = [
        P1_BOTH_WAYS,
        pathway(3, "EN", "MISSING", bidirectional=1),
        pathway(4, "MISSING", "P2", bidirectional=1),
    ]
    assert fire(BASE_STOPS, pathways) == []


def test_a_duplicated_stop_id_is_seeded_from_every_row_not_just_the_first():
    """Measured on `pr14`: id `X` appears as a platform and then as an entrance, and the jar is silent.

    `stopTable.getEntities()` holds both rows, so the entrance row seeds the traversal. Seeding from
    an index keyed by stop id keeps only the first row, sees a platform, seeds nothing, and reports
    both `X` and the platform behind it. That was a real defect here, found by review.
    """
    stops = [
        stop(2, "ST", "Station", STATION),
        stop(3, "X", "Dup Platform", PLATFORM, "ST"),
        stop(4, "X", "Dup Entrance", ENTRANCE, "ST"),
        stop(5, "P", "Platform", PLATFORM, "ST"),
    ]
    assert fire(stops, [pathway(2, "X", "P", bidirectional=1)]) == []


def test_a_feed_with_no_pathways_reports_nothing():
    """Every station is exempt when nothing has pathways, so the rule returns before searching."""
    assert fire(BASE_STOPS, []) == []
