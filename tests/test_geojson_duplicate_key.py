"""duplicate_geo_json_key, which upstream emits while indexing the feature collection.

Measured on probes `dgk1` through `dgk6`. Not a rule: upstream reports it from
`GtfsGeoJsonFeaturesContainer.setupIndices` during loading rather than from any validator, so it has
no registry entry and is tested through `geojson.parse` like the parser's other codes.
"""

from __future__ import annotations

from geojsonfeed import collection, contexts, feature, run
from gtfs_validator.table_status import TableStatus

CODE = "duplicate_geo_json_key"


def fire(*features):
    _, found, load = run(collection(*features))
    return contexts(found, CODE), load


def test_two_features_sharing_an_id_report_once():
    """Measured on `dgk1`: the indices are 0-based."""
    reported, _ = fire(feature(), feature())
    assert reported == [{"featureId": "L1", "firstIndex": 0, "secondIndex": 1}]


def test_distinct_ids_are_silent():
    """The negative case for the whole code."""
    reported, load = fire(feature(), feature(id="L2"))
    assert reported == []
    assert load.status is TableStatus.PARSABLE_HEADERS_AND_ROWS


def test_a_third_occurrence_reports_against_the_first_not_the_previous():
    """Measured on `dgk2`: the id map is never overwritten, so firstIndex stays 0.

    A last-wins map gives firstIndex 1 for the second notice, which is what this rules out.
    """
    reported, _ = fire(feature(), feature(), feature(id="L2"), feature())
    assert reported == [
        {"featureId": "L1", "firstIndex": 0, "secondIndex": 1},
        {"featureId": "L1", "firstIndex": 0, "secondIndex": 3},
    ]


def test_one_feature_missing_an_element_suppresses_the_whole_pass():
    """Measured on `dgk5`: L1, a feature with no geometry, L1, and the jar reports nothing.

    A single unparsable feature makes the file UNPARSABLE_ROWS, and upstream then builds the
    container with its status-only constructor, so setupIndices never runs. Reporting the duplicate
    here would be a notice on a feed the jar passes, which is why the pass sits after that check
    rather than inside the loop that builds the list.
    """
    broken = feature(id="BROKEN")
    del broken["geometry"]
    reported, load = fire(feature(), broken, feature())
    assert reported == []
    assert load.status is TableStatus.UNPARSABLE_ROWS


def test_a_numeric_id_is_compared_in_its_converted_form():
    """Measured on `dgk9`: ids `"7"`, `7`, `7` report `featureId "7.0"` at indices 1 and 2.

    A numeric id is not dropped, which is what an earlier version of this file claimed: it is
    converted to Java's double form, so `7` becomes `"7.0"` and collides with another `7` but not
    with the string `"7"`. That is also why `dgk6`, which pairs `"1"` with `1`, is silent.

    The indices double as a check that the notice reports the position in the JSON array. A
    first-occurrence index of 0 here would mean something was numbering surviving features instead.
    """
    reported, load = fire(feature(id="7"), feature(id=7), feature(id=7))
    assert reported == [{"featureId": "7.0", "firstIndex": 1, "secondIndex": 2}]
    assert load.status is TableStatus.PARSABLE_HEADERS_AND_ROWS
