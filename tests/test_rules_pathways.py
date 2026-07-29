"""The three pathway validators that read only pathways.txt and stops.txt.

Every expectation is the jar's output on `pwfeed`, whose stops cover each location type
and whose nine pathways cover each branch plus two controls: a generic node with two
distinct neighbours, and a generic node with no pathways at all.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")

STOP, STATION, ENTRANCE, GENERIC_NODE, BOARDING_AREA = 0, 1, 2, 3, 4
NOT_ACCESSIBLE = 1


def stop(number, stop_id, name, location_type, parent=None, platform_code=None, access=None):
    return {
        "_row_number": number,
        "stop_id": stop_id,
        "stop_name": name,
        "location_type": location_type,
        "parent_station": parent,
        "platform_code": platform_code,
        "stop_access": access,
    }


def pathway(number, pathway_id, from_stop, to_stop):
    return {
        "_row_number": number,
        "pathway_id": pathway_id,
        "from_stop_id": from_stop,
        "to_stop_id": to_stop,
        "pathway_mode": 1,
        "is_bidirectional": 0,
    }


STOPS = [
    stop(2, "ST1", "Station", STATION),
    stop(3, "P1", "Plat One", STOP, "ST1"),
    stop(4, "P2", "Plat Two", STOP, "ST1"),
    stop(5, "BA1", "Board One", BOARDING_AREA, "P1"),
    stop(6, "G1", "Node One", GENERIC_NODE, "ST1"),
    stop(7, "G2", "Node Two", GENERIC_NODE, "ST1"),
    stop(8, "G3", "Node Three", GENERIC_NODE, "ST1"),
    stop(9, "G4", "Node Four", GENERIC_NODE, "ST1"),
    stop(10, "E1", "Entrance", ENTRANCE, "ST1"),
    stop(11, "P3", "Plat Three", STOP, "ST1", platform_code="Z", access=NOT_ACCESSIBLE),
    stop(12, "P4", "Plat Four", STOP, "ST1", access=NOT_ACCESSIBLE),
]
PATHWAYS = [
    pathway(2, "PW1", "P1", "E1"),
    pathway(3, "PW2", "ST1", "P2"),
    pathway(4, "PW3", "G1", "P2"),
    pathway(5, "PW4", "G2", "P2"),
    pathway(6, "PW5", "P2", "G2"),
    pathway(7, "PW6", "G3", "P1"),
    pathway(8, "PW7", "G3", "P2"),
    pathway(9, "PW8", "P3", "P2"),
    pathway(10, "PW9", "P4", "P4"),
]

MEASURED = {
    "pathway_to_platform_with_boarding_areas": [
        {"csvRowNumber": 2, "pathwayId": "PW1", "fieldName": "from_stop_id", "stopId": "P1"},
        {"csvRowNumber": 7, "pathwayId": "PW6", "fieldName": "to_stop_id", "stopId": "P1"},
    ],
    "pathway_to_wrong_location_type": [
        {"csvRowNumber": 3, "pathwayId": "PW2", "fieldName": "from_stop_id", "stopId": "ST1"},
    ],
    "pathway_dangling_generic_node": [
        {"csvRowNumber": 6, "stopId": "G1", "stopName": "Node One", "parentStation": "ST1"},
        {"csvRowNumber": 7, "stopId": "G2", "stopName": "Node Two", "parentStation": "ST1"},
    ],
    "pathway_to_stop_with_access_outside_of_station_pathways": [
        {"csvRowNumber": 9, "pathwayId": "PW8", "stopId": "P3", "platformCode": "Z"},
        # Measured: an absent platform_code renders "" rather than dropping the key, even
        # though the Java field is non-final and could have been left null.
        {"csvRowNumber": 10, "pathwayId": "PW9", "stopId": "P4", "platformCode": ""},
    ],
}


def fire(code, stops=None, pathways=None, columns=None):
    registry.load_rules()
    tables = {
        "stops.txt": STOPS if stops is None else stops,
        "pathways.txt": PATHWAYS if pathways is None else pathways,
    }
    return [n.context for n in registry.FILE_REGISTRY[code].func(FakeFeed(tables), CTX)]


@pytest.mark.parametrize(("code", "expected"), sorted(MEASURED.items()))
def test_pathway_rule_matches_the_jar(code, expected):
    assert fire(code) == expected


def test_a_generic_node_needs_exactly_one_distinct_neighbour():
    """G2 has two pathways but one neighbour and is reported; G3 has two neighbours and is
    not; G4 has no pathways and is not. Upstream tests the size of a *set* of the far
    endpoints, so zero and two both pass and only one fails."""
    reported = [n["stopId"] for n in fire("pathway_dangling_generic_node")]
    assert reported == ["G1", "G2"]
    assert "G3" not in reported
    assert "G4" not in reported


def test_the_access_rule_reports_a_self_loop_once():
    """PW9 has the same flagged stop at both ends. Upstream guards with a set of emitted
    stop ids, so the pathway draws one notice rather than two."""
    got = fire(
        "pathway_to_stop_with_access_outside_of_station_pathways",
        pathways=[pathway(10, "PW9", "P4", "P4")],
    )
    assert got == [{"csvRowNumber": 10, "pathwayId": "PW9", "stopId": "P4", "platformCode": ""}]


def test_the_access_rule_needs_the_stop_access_column():
    """shouldCallValidate is a header test on stops.stop_access, so a feed without the
    column stays silent even if the rule would otherwise have something to say."""
    stops = [dict(row) for row in STOPS]
    for row in stops:
        row.pop("stop_access", None)
    assert fire("pathway_to_stop_with_access_outside_of_station_pathways", stops=stops) == []


def test_an_endpoint_naming_a_missing_stop_is_skipped():
    """Upstream returns early when byStopId is empty: the broken reference is
    foreign_key_violation's to report, not this rule's."""
    pathways = [pathway(2, "PWX", "NOPE", "ALSO_NOPE")]
    assert fire("pathway_to_wrong_location_type", pathways=pathways) == []
    assert fire("pathway_to_platform_with_boarding_areas", pathways=pathways) == []
