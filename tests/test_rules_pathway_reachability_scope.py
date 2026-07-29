"""Which locations `pathway_unreachable_location` reports, and what the notice carries.

Three of these are exemptions rather than checks, and each is the opposite of the obvious
implementation: an entrance is never reported however unreachable, a platform that has boarding
areas is exempt in favour of them, and a station with no pathways is exempt entirely.

The graph search that decides reachability is next door in `test_rules_pathway_reachability`.
"""

from __future__ import annotations

import pytest

from fakefeed import FakeFeed
from gtfs_validator.manifest import load_manifest
from gtfs_validator.rules import registry
from reachfeed import (
    BASE_STOPS,
    BOARDING_AREA,
    CODE,
    CTX,
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


def test_the_notice_carries_seven_fields():
    """Measured on `pr1`, field for field."""
    assert fire(BASE_STOPS, [P1_BOTH_WAYS]) == [
        {
            "csvRowNumber": 5,
            "stopId": "P2",
            "stopName": "Platform Two",
            "locationType": 0,
            "parentStation": "ST",
            "hasEntrance": False,
            "hasExit": False,
        }
    ]


def test_a_platform_with_boarding_areas_is_exempt_and_they_are_not():
    """Measured on `pr5`: BA1 and BA2 are reported and P2, their parent, is not.

    Upstream's reason is that such a platform need not have incident pathways of its own. The
    exemption is what makes this the opposite of the obvious implementation, which reports three
    locations here.
    """
    stops = [
        *BASE_STOPS,
        stop(6, "BA1", "Boarding A", BOARDING_AREA, "P2"),
        stop(7, "BA2", "Boarding B", BOARDING_AREA, "P2"),
    ]
    reported = fire(stops, [P1_BOTH_WAYS])
    assert [(row["csvRowNumber"], row["stopId"], row["locationType"]) for row in reported] == [
        (6, "BA1", 4),
        (7, "BA2", 4),
    ]


def test_a_generic_node_is_reported_and_a_station_without_pathways_is_not():
    """Measured on `pr6`: P2 and GN are reported, the platform in the quiet station is not.

    A station with no pathways is exempt entirely, which is what stops this rule reporting every
    platform in a feed that happens to carry one pathway somewhere else.
    """
    stops = [
        *BASE_STOPS,
        stop(6, "GN", "Node", GENERIC_NODE, "ST"),
        stop(7, "ST2", "Quiet Station", STATION),
        stop(8, "P3", "Quiet Platform", PLATFORM, "ST2"),
    ]
    assert reported_ids(stops, [P1_BOTH_WAYS]) == ["P2", "GN"]


def test_an_entrance_is_never_reported_however_unreachable():
    """Measured on `pr8`: a second entrance that nothing connects draws nothing.

    Exempt by location type rather than by reachability, so it is silent even though the same test
    applied to a platform in its position reports.
    """
    stops = [*BASE_STOPS, stop(6, "EN2", "Lonely Entrance", ENTRANCE, "ST")]
    pathways = [P1_BOTH_WAYS, pathway(3, "EN", "P2", bidirectional=1)]
    assert fire(stops, pathways) == []


def test_a_location_with_no_parent_station_is_not_reported():
    """`getIncludingStation` finding nothing is a skip, so a bare stop is exempt.

    Which is most stops in most feeds: this rule is about stations, and a stop belonging to no
    station cannot be in one that has pathways.
    """
    stops = [*BASE_STOPS, stop(6, "LONE", "Lone Stop", PLATFORM)]
    assert reported_ids(stops, [P1_BOTH_WAYS]) == ["P2"]


def test_a_present_but_empty_parent_station_resolves_to_no_station():
    """Measured on `pr11`: such a platform is not reported, and P2 still is.

    `hasParentStation()` is a presence test, so an empty parent is a **hop** to the station whose id
    is the empty string rather than the end of the walk. No such station exists, so the walk returns
    nothing and the location is exempt. Reading the empty parent as "no parent" reaches the same
    answer by a different route, which is why the case is pinned rather than assumed.
    """
    stops = [*BASE_STOPS, stop(6, "P3", "Present Empty", PLATFORM, "")]
    assert reported_ids(stops, [P1_BOTH_WAYS]) == ["P2"]


def test_a_parent_cycle_terminates_and_reports_neither_location():
    """Measured on `pr12`: two platforms each naming the other as parent, and the jar is silent.

    The walk is bounded at three lookups precisely because a feed can contain this, and upstream
    says so in a comment. Without the bound the rule would not terminate.
    """
    stops = [
        *BASE_STOPS,
        stop(6, "C1", "Cycle One", PLATFORM, "C2"),
        stop(7, "C2", "Cycle Two", PLATFORM, "C1"),
    ]
    assert reported_ids(stops, [P1_BOTH_WAYS]) == ["P2"]


def test_a_boarding_area_two_levels_down_is_found_and_exempts_its_platform():
    """Measured on `pr13`: nothing at all is reported.

    The boarding area's station is two hops up, inside the three-hop bound, so it is in scope; a
    pathway reaches it, so it is silent. Its platform is exempt for having a boarding area at all.
    One row therefore silences two locations, which is the exemption and the walk interacting.
    """
    stops = [*BASE_STOPS, stop(6, "BA", "Boarding", BOARDING_AREA, "P2")]
    assert fire(stops, [P1_BOTH_WAYS, pathway(3, "EN", "BA", bidirectional=1)]) == []


def test_a_platform_is_exempt_for_any_child_not_only_a_boarding_area():
    """Measured on `pr17`: P2's only child is a generic node, and P2 is still exempt.

    Upstream's condition is `byParentStation(stopId).isEmpty()`, so it is any child at all. Narrowing
    it to boarding areas passes every other test in this module.
    """
    stops = [*BASE_STOPS, stop(6, "GN", "Child Node", GENERIC_NODE, "P2")]
    assert reported_ids(stops, [P1_BOTH_WAYS]) == ["GN"]


def test_a_platform_whose_own_id_is_empty_is_exempt():
    """Measured on `pr15`: the jar is silent about it.

    Because `byParentStation("")` returns every root-level stop, so a location whose `stop_id` is ""
    looks as though it has children. An index that omitted parentless rows reported it, which was a
    real defect and one shared with `pathway_to_platform_with_boarding_areas`.
    """
    stops = [*BASE_STOPS, stop(6, "", "Empty Id", PLATFORM, "ST")]
    assert reported_ids(stops, [P1_BOTH_WAYS]) == ["P2"]


def test_the_station_walk_gives_up_after_three_lookups():
    """Measured on `pr18`: a boarding area three deep is reported, one four deep is not.

    `ST < P2 < BA1 < BA2`, and from BA2 the station is the fourth lookup. Raising the bound to four
    would report BA2 as well, and the cycle test above still terminates under that change, so this
    is the case that pins the number.
    """
    stops = [
        *BASE_STOPS,
        stop(6, "BA1", "Boarding One", BOARDING_AREA, "P2"),
        stop(7, "BA2", "Boarding Two", BOARDING_AREA, "BA1"),
    ]
    assert reported_ids(stops, [P1_BOTH_WAYS]) == ["BA1"]


def test_a_station_whose_own_id_is_empty_is_still_a_station():
    """Measured on `pr19`: P2 is reported with `parentStation` as "".

    The parent test is a presence test, so a `parent_station` of "" hops to the station whose id is
    "" rather than ending the walk. Reading it as truthiness exempts the platform instead. This is
    also the only case that puts an empty string in the `parentStation` field.
    """
    stops = [
        stop(2, "", "Empty Station", STATION),
        stop(3, "EN", "Entrance", ENTRANCE, ""),
        stop(4, "P1", "Platform One", PLATFORM, ""),
        stop(5, "P2", "Platform Two", PLATFORM, ""),
    ]
    reported = fire(stops, [pathway(2, "EN", "P1", bidirectional=1)])
    assert [(row["stopId"], row["parentStation"]) for row in reported] == [("P2", "")]


def test_notices_come_out_in_stops_file_order():
    """The loop is over `stopTable.getEntities()`, which is file order and not a hash order.

    Pinned with the reported locations deliberately out of id order, so a port that walked an index
    keyed by stop id would produce a different sequence.
    """
    stops = [
        stop(2, "ST", "Station", STATION),
        stop(3, "EN", "Entrance", ENTRANCE, "ST"),
        stop(4, "ZZ", "Zulu", PLATFORM, "ST"),
        stop(5, "AA", "Alpha", PLATFORM, "ST"),
        stop(6, "MM", "Mike", PLATFORM, "ST"),
    ]
    assert reported_ids(stops, [pathway(2, "EN", "QQ", bidirectional=1)]) == ["ZZ", "AA", "MM"]


def test_an_absent_location_type_is_a_platform():
    """The column defaults to 0, so a blank cell is a platform reported as `locationType` 0."""
    stops = [
        stop(2, "ST", "Station", STATION),
        stop(3, "EN", "Entrance", ENTRANCE, "ST"),
        stop(4, "P1", "Platform One", None, "ST"),
    ]
    reported = fire(stops, [pathway(2, "EN", "NOWHERE", bidirectional=1)])
    assert [(row["stopId"], row["locationType"]) for row in reported] == [("P1", 0)]


def test_a_duplicated_id_resolves_to_the_first_row_and_reports_an_empty_parent():
    """Measured on `pr21`, which settles two questions at once.

    Id `ST` is a station first and a parentless platform second, and the pathway starts at `ST`
    itself so the station has pathways without having children. The jar reports the **platform**
    row, at csvRowNumber 3, with `parentStation` as "".

    So `byStopId` resolves a duplicated id to the *first* row, which is what makes the platform row
    in scope at all: resolving to the last row would break the walk on a parentless platform and
    report nothing. And it is the only reachable case where the reported location's own
    `parent_station` is absent, so it is the only test that can see `parentStation` rendering as ""
    rather than as null.
    """
    stops = [
        stop(2, "ST", "Station", STATION),
        stop(3, "ST", "Dup Platform", PLATFORM),
        stop(4, "OTHER", "Other", PLATFORM),
    ]
    reported = fire(stops, [pathway(2, "ST", "OTHER", bidirectional=1)])
    assert [(row["csvRowNumber"], row["stopId"], row["parentStation"]) for row in reported] == [
        (3, "ST", "")
    ]


def test_an_absent_stop_name_renders_as_an_empty_string():
    """A Java `String` field, so an unset one is "" rather than null or an omitted key."""
    stops = [
        stop(2, "ST", "Station", STATION),
        stop(3, "EN", "Entrance", ENTRANCE, "ST"),
        {"_row_number": 4, "stop_id": "P1", "location_type": PLATFORM, "parent_station": "ST"},
    ]
    reported = fire(stops, [pathway(2, "EN", "NOWHERE", bidirectional=1)])
    assert reported[0]["stopName"] == ""


def test_the_context_keys_are_in_the_order_upstream_declares_them():
    """Invisible to everything else: the differential harness sorts keys before diffing.

    Pinned against `canonical_notices.json`, generated from upstream at the pin, so a field reordered
    upstream fails this rather than silently agreeing with a retyped list.
    """
    reported = fire(BASE_STOPS, [P1_BOTH_WAYS])[0]
    assert list(reported) == list(load_manifest().context_fields_of(CODE))


def test_each_context_value_has_the_type_the_manifest_declares():
    """`hasEntrance` and `hasExit` must be `bool` and `locationType` must not be.

    Python holds `1 == 1.0 == True` and `bool` subclasses `int`, so dict equality cannot see either
    mistake and an `isinstance` check would let a boolean pass as an integer. The report writer
    passes the context through untouched, so `true` where the jar writes `1` would ship.
    """
    reported = fire(BASE_STOPS, [P1_BOTH_WAYS])[0]
    for field, kind in load_manifest().context_fields_of(CODE).items():
        value = reported[field]
        expected = {"integer": int, "string": str, "boolean": bool}[kind]
        assert type(value) is expected, f"{field} is {type(value).__name__}, not {kind}"


@pytest.mark.parametrize("failed", ["stops.txt", "pathways.txt"])
def test_a_failed_table_silences_the_rule(failed):
    """Both containers are injected, so either one failing to index stops the validator."""
    registry.load_rules()
    view = FakeFeed(
        {"stops.txt": BASE_STOPS, "pathways.txt": [P1_BOTH_WAYS]},
        unindexable=frozenset({failed}),
    )
    with pytest.raises(Exception, match=failed):
        list(registry.FILE_REGISTRY[CODE].func(view, CTX))
