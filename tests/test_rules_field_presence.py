"""What `hasX()` means, at every site that asks it.

Upstream's generated `hasX()` reports whether the column carried a value, and the loader records
an empty one for a quoted whitespace cell. So a cell of `" "` is **present**, and a rule reading
presence as truthiness gets it backwards in both directions: it invents notices the jar does not
emit and misses ones it does.

The trap is that `hasX()` and `field().isEmpty()` read identically in Python and upstream uses
both, sometimes in the same method. `StopNameValidator` asks `stopName().isEmpty()` at line 48 and
`hasStopName()` at line 53. Truthiness is right at the first and wrong at the second, so each site
here names which one it mirrors.

Measured on three probes built for this, each carrying its whitespace cells *quoted* so the
loader records them:

- `ps2`: `parent_station` on a station, a platform, an entrance and a stop with `stop_access`
- `tr2`: `field_value`, `record_id` and `field_name` in translations.txt
- `ag2`: `agency_id` in agency.txt, routes.txt and fare_attributes.txt
"""

from __future__ import annotations

import datetime
import json
import zipfile

from fakefeed import FakeFeed
from gtfs_validator.cli import main
from gtfs_validator.context import Context
from gtfs_validator.manifest import load_manifest
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 26), country_code="US")
STOP, STATION, ENTRANCE = 0, 1, 2


def stop_row(row_number, stop_id, name, location_type, **extra):
    return {
        "_row_number": row_number,
        "stop_id": stop_id,
        "stop_name": name,
        "location_type": location_type,
        **extra,
    }


def entity_notices(code, row):
    registry.load_rules()
    return list(registry.REGISTRY[code].func(row, CTX))


def file_notices(code, tables, **kwargs):
    registry.load_rules()
    return list(registry.FILE_REGISTRY[code].func(FakeFeed(tables, **kwargs), CTX))


def entity(code, row):
    """Contexts only, for the presence assertions.

    `test_every_rule_here_reports_its_own_code_at_its_own_severity` is what keeps this from
    hiding a rule that emits the right context under the wrong code: a review pointed out that
    every assertion in this file would pass if it did.
    """
    return [notice.context for notice in entity_notices(code, row)]


def file_rule(code, tables, **kwargs):
    return [notice.context for notice in file_notices(code, tables, **kwargs)]


# --- parent_station, LocationTypeSingleEntityValidator:52 and StopAccessValidator ------------
#
# `hasParentStation()`. An empty parent_station is present, so the *first* branch is taken and
# the else-if chain below it never runs: a platform, an entrance and a stop_access row all draw
# nothing, and a station draws its notice with `parentStation: ""`. Measured on `ps2`.


def test_a_station_whose_empty_parent_station_is_present_is_reported():
    assert entity(
        "station_with_parent_station",
        stop_row(4, "ST_WS", "Station WS", STATION, parent_station=""),
    ) == [{"csvRowNumber": 4, "stopId": "ST_WS", "stopName": "Station WS", "parentStation": ""}]


def test_a_station_with_no_parent_station_at_all_is_not_reported():
    assert (
        entity(
            "station_with_parent_station",
            stop_row(4, "ST", "Station", STATION, parent_station=None),
        )
        == []
    )


def test_a_platform_with_an_empty_parent_station_is_not_reported():
    row = stop_row(5, "PF_WS", "Platform WS", STOP, parent_station="", platform_code="A")
    assert entity("platform_without_parent_station", row) == []


def test_a_platform_with_no_parent_station_is_reported():
    row = stop_row(5, "PF", "Platform", STOP, parent_station=None, platform_code="A")
    assert entity("platform_without_parent_station", row) == [
        {"csvRowNumber": 5, "stopId": "PF", "stopName": "Platform"}
    ]


def test_an_entrance_with_an_empty_parent_station_is_not_reported():
    row = stop_row(6, "EN_WS", "Entrance WS", ENTRANCE, parent_station="")
    assert entity("location_without_parent_station", row) == []


def test_an_entrance_with_no_parent_station_is_reported():
    row = stop_row(6, "EN", "Entrance", ENTRANCE, parent_station=None)
    assert [c["stopId"] for c in entity("location_without_parent_station", row)] == ["EN"]


def test_stop_access_on_a_stop_whose_empty_parent_station_is_present_is_not_reported():
    row = stop_row(7, "AC_WS", "Access WS", STOP, parent_station="", stop_access=1)
    assert entity("stop_access_specified_for_stop_with_no_parent_station", row) == []


def test_stop_access_on_a_stop_with_no_parent_station_is_reported():
    row = stop_row(7, "AC", "Access", STOP, parent_station=None, stop_access=1)
    assert [
        c["stopId"] for c in entity("stop_access_specified_for_stop_with_no_parent_station", row)
    ] == ["AC"]


# --- platform_code, LocationTypeSingleEntityValidator:62 -------------------------------------
#
# The counterexample, and the reason each site above had to be read rather than swept: two lines
# apart from `hasParentStation()`, upstream asks `platformCode().isEmpty()`. Truthiness is right
# here, so an empty platform_code is *not* a platform.


def test_an_empty_platform_code_is_not_a_platform():
    row = stop_row(5, "PF", "Platform", STOP, parent_station=None, platform_code="")
    assert entity("platform_without_parent_station", row) == []


# --- translations.txt, TranslationFieldAndReferenceValidator ---------------------------------
#
# `hasFieldName()`, `hasFieldValue()`, `hasRecordId()`, `hasRecordSubId()`, all presence.
# Measured on `tr2`.

STOPS_TABLE = [
    {"_row_number": 2, "stop_id": "PLAIN", "stop_name": "Plain"},
    {"_row_number": 3, "stop_id": "PLAIN2", "stop_name": "Two"},
]


def translation(row_number, **fields):
    row = {
        "_row_number": row_number,
        "table_name": "stops",
        "field_name": "stop_name",
        "language": "fr",
        "translation": "X",
    }
    row.update(fields)
    return row


def translations_feed(rows):
    return {"stops.txt": STOPS_TABLE, "translations.txt": rows}


def test_an_empty_field_name_is_present_so_the_first_pass_finds_nothing():
    # The first pass returning anything silences the other three codes, so reading this as
    # missing would have hidden the reference checks for the whole file.
    rows = [translation(2, field_name="", record_id="PLAIN")]
    missing = file_rule("missing_required_field", translations_feed(rows))
    assert [c for c in missing if c.get("filename") == "translations.txt"] == []


def test_an_absent_field_name_is_still_missing():
    rows = [translation(2, field_name=None, record_id="PLAIN")]
    missing = file_rule("missing_required_field", translations_feed(rows))
    assert [c["fieldName"] for c in missing if c.get("filename") == "translations.txt"] == [
        "field_name"
    ]


def test_an_empty_record_id_beside_a_field_value_is_an_unexpected_value():
    # `hasFieldValue()` then `hasRecordId()`: both present, so the id is reported with the empty
    # string upstream stores for it.
    rows = [translation(2, field_value="Plain", record_id="")]
    assert file_rule("translation_unexpected_value", translations_feed(rows)) == [
        {"csvRowNumber": 2, "fieldName": "record_id", "fieldValue": ""}
    ]


def test_an_empty_field_value_still_takes_the_field_value_branch():
    # Present, so the reference lookup never runs and the row's record_id is unexpected instead.
    rows = [translation(3, field_value="", record_id="PLAIN")]
    assert file_rule("translation_unexpected_value", translations_feed(rows)) == [
        {"csvRowNumber": 3, "fieldName": "record_id", "fieldValue": "PLAIN"}
    ]


def test_an_absent_field_value_goes_to_the_reference_lookup():
    rows = [translation(3, field_value=None, record_id="PLAIN")]
    assert file_rule("translation_unexpected_value", translations_feed(rows)) == []


def test_an_empty_record_sub_id_is_unexpected_for_a_single_key_parent():
    # stops.txt has one key column, so record_sub_id is forbidden and an empty one is present.
    rows = [translation(2, field_value=None, record_id="PLAIN", record_sub_id="")]
    assert file_rule("translation_unexpected_value", translations_feed(rows)) == [
        {"csvRowNumber": 2, "fieldName": "record_sub_id", "fieldValue": ""}
    ]


# --- agency_id, AgencyConsistencyValidator and the two *AgencyIdValidators -------------------
#
# `hasAgencyId()` at all four sites. Measured on `ag2`: none of the three whitespace agency_ids
# draws missing_required_agency_id, and the single-agency case draws no missing_recommended_field
# either.

AGENCIES = [
    {"_row_number": 2, "agency_id": "1", "agency_name": "A"},
    {"_row_number": 3, "agency_id": "", "agency_name": "B"},
]


def test_an_empty_agency_id_is_present_so_it_is_not_missing():
    tables = {"agency.txt": AGENCIES, "routes.txt": [], "fare_attributes.txt": []}
    assert file_rule("missing_required_agency_id", tables) == []


def test_an_absent_agency_id_is_missing():
    agencies = [AGENCIES[0], {"_row_number": 3, "agency_id": None, "agency_name": "B"}]
    tables = {"agency.txt": agencies, "routes.txt": [], "fare_attributes.txt": []}
    assert file_rule("missing_required_agency_id", tables) == [
        {"filename": "agency.txt", "csvRowNumber": 3, "agencyName": "B"}
    ]


def test_an_empty_agency_id_on_a_route_is_present_too():
    tables = {
        "agency.txt": AGENCIES,
        "routes.txt": [{"_row_number": 3, "route_id": "R2", "agency_id": ""}],
        "fare_attributes.txt": [],
    }
    assert file_rule("missing_required_agency_id", tables) == []


def test_a_single_agency_with_an_empty_agency_id_draws_no_recommendation():
    # The other half of AgencyConsistencyValidator: one agency, and agency_id is recommended
    # rather than required. Same `hasAgencyId()`, so an empty one satisfies it.
    tables = {"agency.txt": [{"_row_number": 2, "agency_id": "", "agency_name": "A"}]}
    recommended = file_rule("missing_recommended_field", tables)
    assert [c for c in recommended if c.get("fieldName") == "agency_id"] == []


def test_a_single_agency_with_no_agency_id_draws_one():
    tables = {"agency.txt": [{"_row_number": 2, "agency_id": None, "agency_name": "A"}]}
    recommended = file_rule("missing_recommended_field", tables)
    assert [c["fieldName"] for c in recommended if c.get("filename") == "agency.txt"] == [
        "agency_id"
    ]


# --- fare_media.txt and fare_leg_join_rules.txt ---------------------------------------------
#
# `!entity.hasFareMediaName()` and `hasFromStopId() && !hasToStopId()`. Both found by grepping
# again after the first sweep's pattern missed every compound condition.


def test_an_empty_fare_media_name_counts_as_named():
    # Measured on `fm2`: a fare_media of type 2 whose name is a quoted space draws nothing.
    tables = {
        "fare_media.txt": [
            {"_row_number": 2, "fare_media_id": "FM1", "fare_media_name": "", "fare_media_type": 2}
        ]
    }
    named = file_rule("missing_recommended_field", tables)
    assert [c for c in named if c.get("filename") == "fare_media.txt"] == []


def test_an_absent_fare_media_name_is_recommended():
    tables = {
        "fare_media.txt": [
            {
                "_row_number": 2,
                "fare_media_id": "FM1",
                "fare_media_name": None,
                "fare_media_type": 2,
            }
        ]
    }
    named = file_rule("missing_recommended_field", tables)
    assert [c["fieldName"] for c in named if c.get("filename") == "fare_media.txt"] == [
        "fare_media_name"
    ]


def test_an_empty_stop_end_on_a_fare_leg_join_rule_is_present():
    # Measured on `fl2`: an empty to_stop_id beside a real from_stop_id draws no
    # missing_required_field. The jar reports a foreign_key_violation for it instead, which is
    # a code this build does not implement.
    tables = {
        "fare_leg_join_rules.txt": [
            {
                "_row_number": 2,
                "from_network_id": "N1",
                "to_network_id": "N2",
                "from_stop_id": "S1",
                "to_stop_id": "",
            }
        ]
    }
    missing = file_rule("missing_required_field", tables)
    assert [c for c in missing if c.get("filename") == "fare_leg_join_rules.txt"] == []


def test_an_absent_stop_end_on_a_fare_leg_join_rule_is_missing():
    tables = {
        "fare_leg_join_rules.txt": [
            {
                "_row_number": 2,
                "from_network_id": "N1",
                "to_network_id": "N2",
                "from_stop_id": "S1",
                "to_stop_id": None,
            }
        ]
    }
    missing = file_rule("missing_required_field", tables)
    assert [c["fieldName"] for c in missing if c.get("filename") == "fare_leg_join_rules.txt"] == [
        "to_stop_id"
    ]


def test_an_empty_field_value_also_stops_the_reference_lookup_and_the_missing_check():
    # The same input as above, through the two rules that read `resolvable_rows`. Without these,
    # reverting either of them to truthiness would still pass this file: a review pointed out
    # that only translation_unexpected_value was being exercised.
    rows = [translation(3, field_value="", record_id="PLAIN")]
    assert file_rule("translation_foreign_key_violation", translations_feed(rows)) == []
    missing = file_rule("missing_required_field", translations_feed(rows))
    assert [c for c in missing if c.get("filename") == "translations.txt"] == []


def test_the_first_wrong_presence_stops_the_row_before_the_second():
    # `isMissingOrUnexpectedField(record_id) || isMissingOrUnexpectedField(record_sub_id)` is
    # short-circuiting. stops.txt wants record_id and forbids record_sub_id, so a row with
    # neither right draws one notice about record_id and nothing about record_sub_id.
    rows = [translation(2, field_value=None, record_id=None, record_sub_id="SUB")]
    missing = file_rule("missing_required_field", translations_feed(rows))
    assert [c["fieldName"] for c in missing if c.get("filename") == "translations.txt"] == [
        "record_id"
    ]
    assert file_rule("translation_unexpected_value", translations_feed(rows)) == []


# --- the four sites a review found after the first sweep -------------------------------------


def test_a_present_empty_record_id_is_looked_up_rather_than_skipped():
    # `isMissingOrUnexpectedField` is handed `hasRecordId()`, so an empty one satisfies a parent
    # that wants an id and upstream goes on to look up the empty key. Measured on `fk1`, where
    # the jar reports translation_foreign_key_violation with `recordId: ""`.
    rows = [translation(2, field_value=None, record_id="", record_sub_id=None)]
    assert file_rule("translation_foreign_key_violation", translations_feed(rows)) == [
        {"csvRowNumber": 2, "tableName": "stops", "recordId": "", "recordSubId": ""}
    ]


def test_an_empty_record_id_that_does_resolve_draws_nothing():
    # The other half: a stops.txt row stored under the empty id makes the lookup succeed, which
    # is what stops the test above from passing for the wrong reason.
    stops = [{"_row_number": 2, "stop_id": "", "stop_name": "Empty"}]
    rows = [translation(2, field_value=None, record_id="", record_sub_id=None)]
    tables = {"stops.txt": stops, "translations.txt": rows}
    assert file_rule("translation_foreign_key_violation", tables) == []


def test_a_boarding_area_whose_empty_parent_station_resolves_is_checked():
    # `!location.hasParentStation()` in ParentStationValidator. Measured on `wp1`.
    stops = [
        {"_row_number": 2, "stop_id": "", "stop_name": "Empty parent", "location_type": 1},
        {
            "_row_number": 3,
            "stop_id": "BA",
            "stop_name": "Area",
            "location_type": 4,
            "parent_station": "",
        },
    ]
    got = file_rule("wrong_parent_location_type", {"stops.txt": stops})
    assert [(c["stopId"], c["parentStation"], c["parentLocationType"]) for c in got] == [
        ("BA", "", 1)
    ]


def test_the_coordinate_walk_follows_a_present_empty_parent():
    # StopUtil.getStopOrParentLatLng asks `hasParentStation()` before hopping, so a child whose
    # parent_station is empty still inherits the station's position. Measured on `sc1`, where
    # stopping the walk invented a transfer_distance_too_large of 8652 km against the origin.
    from gtfs_validator.rules._shared.stop_coordinates import optional_coordinates_of, stops_by_id

    stops = [
        {
            "_row_number": 2,
            "stop_id": "A",
            "stop_name": "Child",
            "location_type": 0,
            "parent_station": "",
            "stop_lat": None,
            "stop_lon": None,
        },
        {
            "_row_number": 3,
            "stop_id": "",
            "stop_name": "Empty parent",
            "location_type": 1,
            "stop_lat": 40.1,
            "stop_lon": -74.0,
        },
    ]
    by_id = stops_by_id(FakeFeed({"stops.txt": stops}))
    assert optional_coordinates_of(by_id, "A") == (40.1, -74.0)


def test_the_coordinate_walk_stops_at_an_absent_parent():
    from gtfs_validator.rules._shared.stop_coordinates import optional_coordinates_of, stops_by_id

    stops = [
        {
            "_row_number": 2,
            "stop_id": "A",
            "stop_name": "Child",
            "location_type": 0,
            "parent_station": None,
            "stop_lat": None,
            "stop_lon": None,
        },
    ]
    by_id = stops_by_id(FakeFeed({"stops.txt": stops}))
    assert optional_coordinates_of(by_id, "A") is None


def test_a_location_group_member_with_an_empty_stop_id_still_serves_it():
    # LocationHasStopTimesValidator adds the member's stop id unconditionally once the group is
    # resolved, so the stop stored under the empty id is served. Measured on `lg1`.
    from gtfs_validator.rules._shared.stop_time_usage import stops_reached_through_location_groups

    tables = {
        "stop_times.txt": [
            {
                "_row_number": 2,
                "trip_id": "T1",
                "stop_id": None,
                "location_group_id": "G",
                "stop_sequence": 1,
            }
        ],
        "location_group_stops.txt": [{"_row_number": 2, "location_group_id": "G", "stop_id": ""}],
    }
    assert stops_reached_through_location_groups(FakeFeed(tables)) == {""}


def test_a_quoted_whitespace_cell_reaches_the_rule_as_present_end_to_end(tmp_path):
    """Everything else here injects `""` straight into a FakeFeed.

    That leaves the two halves untied: a loader that turned a quoted whitespace cell back into
    `None` would pass every other test in this file, and the whole point is that it does not.
    One feed, quoted cell to notice.
    """
    stops = (
        "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
        "S1,One,40.10,-74.0,0,\n"
        "S2,Two,40.20,-74.0,0,\n"
        'ST,Station,40.30,-74.0,1," "\n'
    )
    tables = {
        "agency.txt": (
            "agency_id,agency_name,agency_url,agency_timezone\n"
            "1,Acme,https://example.com,America/New_York\n"
        ),
        "routes.txt": "route_id,agency_id,route_short_name,route_type\nR1,1,10,3\n",
        "trips.txt": "route_id,service_id,trip_id\nR1,WEEK,T1\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\nT1,08:10:00,08:10:00,S2,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
            "start_date,end_date\nWEEK,1,1,1,1,1,0,0,20260101,20261231\n"
        ),
        "stops.txt": stops,
    }
    feed = tmp_path / "feed.zip"
    with zipfile.ZipFile(feed, "w") as archive:
        for name, body in tables.items():
            archive.writestr(name, body)
    out = tmp_path / "out"
    main(["-i", str(feed), "-o", str(out), "-d", "2026-06-01"])
    report = json.loads((out / "report.json").read_text())
    samples = {n["code"]: n["sampleNotices"] for n in report["notices"]}
    assert samples.get("station_with_parent_station") == [
        {"csvRowNumber": 4, "stopId": "ST", "stopName": "Station", "parentStation": ""}
    ]


def test_every_rule_here_reports_its_own_code_at_its_own_severity():
    """The helpers above return contexts, so nothing else in this file can see either.

    Written after a review observed that a rule emitting the right context under the wrong code
    would pass every other assertion here. One positive case per rule, checked against the
    generated manifest rather than a retyped list, so a severity changed upstream fails this.
    """
    manifest = load_manifest()
    cases = [
        entity_notices(
            "station_with_parent_station",
            stop_row(4, "ST", "Station", STATION, parent_station=""),
        ),
        entity_notices(
            "platform_without_parent_station",
            stop_row(5, "PF", "Platform", STOP, parent_station=None, platform_code="A"),
        ),
        entity_notices(
            "location_without_parent_station",
            stop_row(6, "EN", "Entrance", ENTRANCE, parent_station=None),
        ),
        entity_notices(
            "stop_access_specified_for_stop_with_no_parent_station",
            stop_row(7, "AC", "Access", STOP, parent_station=None, stop_access=1),
        ),
        file_notices(
            "missing_required_agency_id",
            {
                "agency.txt": [
                    AGENCIES[0],
                    {"_row_number": 3, "agency_id": None, "agency_name": "B"},
                ],
                "routes.txt": [],
                "fare_attributes.txt": [],
            },
        ),
        file_notices(
            "translation_unexpected_value",
            translations_feed([translation(2, field_value="Plain", record_id="")]),
        ),
    ]
    for notices in cases:
        assert len(notices) == 1
        notice = notices[0]
        assert notice.severity is manifest.severity_of(notice.code), notice.code
