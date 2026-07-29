"""The five remaining single-entity validators in plan 3's cohort.

Expected values measured against the jar on a feed carrying attributions,
pathways, feed_info, timeframes and fare_transfer_rules.
"""

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.notices import Severity
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 24), country_code="US")

# GtfsAttributionRole: 0 not assigned, 1 assigned.
ASSIGNED = 1
# GtfsPathwayMode 7 is an exit gate; is_bidirectional 1 means bidirectional.
EXIT_GATE = 7
BIDIRECTIONAL = 1
TWENTY_FOUR_HOURS = 24 * 3600


def fire(code, row):
    registry.load_rules()
    return list(registry.REGISTRY[code].func(row, CTX))


def attribution(**fields):
    row = {
        "attribution_id": "A1",
        "is_producer": None,
        "is_operator": None,
        "is_authority": None,
        "_row_number": 2,
    }
    row.update(fields)
    return row


def test_an_attribution_with_no_role_is_reported():
    notices = fire("attribution_without_role", attribution())
    assert [n.context for n in notices] == [{"csvRowNumber": 2, "attributionId": "A1"}]


def test_an_attribution_with_any_role_is_not_reported():
    for field in ("is_producer", "is_operator", "is_authority"):
        assert fire("attribution_without_role", attribution(**{field: ASSIGNED})) == [], field


def test_a_blank_attribution_id_is_reported_as_an_empty_string():
    # attribution_id is optional and the generated entity returns the String
    # default rather than null, so the jar prints "" rather than dropping the
    # key. Gson only omits a field that is actually null.
    notices = fire("attribution_without_role", attribution(attribution_id=None, _row_number=6))
    assert [n.context for n in notices] == [{"csvRowNumber": 6, "attributionId": ""}]


def test_a_bidirectional_exit_gate_is_reported():
    notices = fire(
        "bidirectional_exit_gate",
        {"pathway_mode": EXIT_GATE, "is_bidirectional": BIDIRECTIONAL, "_row_number": 2},
    )
    assert [n.context for n in notices] == [
        {"csvRowNumber": 2, "pathwayMode": 7, "isBidirectional": 1}
    ]


def test_a_unidirectional_gate_or_another_mode_is_not_reported():
    for mode, bidirectional in ((EXIT_GATE, 0), (1, BIDIRECTIONAL)):
        assert (
            fire(
                "bidirectional_exit_gate",
                {"pathway_mode": mode, "is_bidirectional": bidirectional, "_row_number": 2},
            )
            == []
        ), (mode, bidirectional)


def test_feed_info_without_a_contact_is_reported():
    notices = fire(
        "missing_feed_contact_email_and_url",
        {"feed_contact_email": None, "feed_contact_url": None, "_row_number": 2},
    )
    assert [n.context for n in notices] == [{"csvRowNumber": 2}]


def test_a_blank_contact_counts_as_absent():
    # FeedContactValidator tests isBlank() as well as presence, which is the only
    # place in this cohort that treats whitespace as missing.
    notices = fire(
        "missing_feed_contact_email_and_url",
        {"feed_contact_email": "   ", "feed_contact_url": None, "_row_number": 2},
    )
    assert len(notices) == 1


def test_either_contact_alone_is_enough():
    for field in ("feed_contact_email", "feed_contact_url"):
        row = {"feed_contact_email": None, "feed_contact_url": None, "_row_number": 2}
        row[field] = "https://example.com"
        assert fire("missing_feed_contact_email_and_url", row) == [], field


def test_a_timeframe_with_only_one_bound_is_reported():
    for start, end in ((3600, None), (None, 7200)):
        notices = fire(
            "timeframe_only_start_or_end_time_specified",
            {"start_time": start, "end_time": end, "_row_number": 2},
        )
        assert [n.context for n in notices] == [{"csvRowNumber": 2}]


def test_a_timeframe_with_both_or_neither_bound_is_not_reported():
    # The check is an exclusive or, so a row with neither bound is fine.
    for start, end in ((3600, 7200), (None, None)):
        assert (
            fire(
                "timeframe_only_start_or_end_time_specified",
                {"start_time": start, "end_time": end, "_row_number": 2},
            )
            == []
        ), (start, end)


def test_both_timeframe_bounds_are_checked_independently():
    notices = fire(
        "timeframe_start_or_end_time_greater_than_twenty_four_hours",
        {
            "start_time": TWENTY_FOUR_HOURS + 1,
            "end_time": TWENTY_FOUR_HOURS + 2,
            "_row_number": 6,
        },
    )
    assert [n.context for n in notices] == [
        {"csvRowNumber": 6, "fieldName": "start_time", "time": "24:00:01"},
        {"csvRowNumber": 6, "fieldName": "end_time", "time": "24:00:02"},
    ]


def test_exactly_twenty_four_hours_is_not_reported():
    # isAfter, not isAfterOrEqual.
    assert (
        fire(
            "timeframe_start_or_end_time_greater_than_twenty_four_hours",
            {
                "start_time": TWENTY_FOUR_HOURS,
                "end_time": TWENTY_FOUR_HOURS,
                "_row_number": 7,
            },
        )
        == []
    )


def test_a_duration_limit_without_a_type_is_reported():
    notices = fire(
        "fare_transfer_rule_duration_limit_without_type",
        {"duration_limit": 3600, "duration_limit_type": None, "_row_number": 2},
    )
    assert [n.context for n in notices] == [{"csvRowNumber": 2}]


def test_a_type_without_a_duration_limit_is_reported():
    notices = fire(
        "fare_transfer_rule_duration_limit_type_without_duration_limit",
        {"duration_limit": None, "duration_limit_type": 0, "_row_number": 3},
    )
    assert [n.context for n in notices] == [{"csvRowNumber": 3}]


def test_neither_is_reported_when_both_or_neither_are_present():
    for limit, limit_type in ((3600, 0), (None, None)):
        row = {"duration_limit": limit, "duration_limit_type": limit_type, "_row_number": 2}
        assert fire("fare_transfer_rule_duration_limit_without_type", row) == []
        assert fire("fare_transfer_rule_duration_limit_type_without_duration_limit", row) == []


def fire_file(code, tables):
    registry.load_rules()
    return list(registry.FILE_REGISTRY[code].func(FakeFeed(tables), CTX))


FERRY, BUS = 4, 3


def test_a_ferry_trip_without_a_bike_answer_is_reported():
    # Measured: on a ferry route, a blank bikes_allowed, an explicit 0 and an
    # out-of-enum 9 all draw the notice, while 1 and 2 do not and a bus route's
    # trips are untouched. The out-of-enum case reaches here as -1 only because
    # the store folds it to UNRECOGNIZED.
    tables = {
        "routes.txt": [
            {"route_id": "F1", "route_type": FERRY},
            {"route_id": "B1", "route_type": BUS},
        ],
        "trips.txt": [
            {"route_id": "F1", "trip_id": "T_absent", "bikes_allowed": None, "_row_number": 2},
            {"route_id": "F1", "trip_id": "T_zero", "bikes_allowed": 0, "_row_number": 3},
            {"route_id": "F1", "trip_id": "T_yes", "bikes_allowed": 1, "_row_number": 4},
            {"route_id": "F1", "trip_id": "T_no", "bikes_allowed": 2, "_row_number": 5},
            {"route_id": "F1", "trip_id": "T_bad", "bikes_allowed": -1, "_row_number": 6},
            {"route_id": "B1", "trip_id": "T_bus", "bikes_allowed": None, "_row_number": 7},
        ],
    }
    assert [n.context for n in fire_file("missing_bike_allowance", tables)] == [
        {"csvRowNumber": 2, "routeId": "F1", "tripId": "T_absent"},
        {"csvRowNumber": 3, "routeId": "F1", "tripId": "T_zero"},
        {"csvRowNumber": 6, "routeId": "F1", "tripId": "T_bad"},
    ]


def test_a_feed_with_no_ferry_route_reports_nothing():
    tables = {
        "routes.txt": [{"route_id": "B1", "route_type": BUS}],
        "trips.txt": [{"route_id": "B1", "trip_id": "T1", "bikes_allowed": None, "_row_number": 2}],
    }
    assert fire_file("missing_bike_allowance", tables) == []


CODE = "route_networks_specified_in_more_than_one_file"


def test_a_network_named_in_routes_and_both_files_draws_two_notices():
    # Measured: two notices, naming route_networks.txt then networks.txt.
    tables = {
        "routes.txt": [{"route_id": "R1", "network_id": "N1"}],
        "route_networks.txt": [{"network_id": "N1", "route_id": "R1"}],
        "networks.txt": [{"network_id": "N1"}],
    }
    assert [n.context for n in fire_file(CODE, tables)] == [
        {"fieldName": "network_id", "fileNameA": "routes.txt", "fileNameB": "route_networks.txt"},
        {"fieldName": "network_id", "fileNameA": "routes.txt", "fileNameB": "networks.txt"},
    ]


def test_only_the_present_conflicting_file_is_named():
    tables = {
        "routes.txt": [{"route_id": "R1", "network_id": "N1"}],
        "route_networks.txt": [{"network_id": "N1", "route_id": "R1"}],
    }
    assert [n.context["fileNameB"] for n in fire_file(CODE, tables)] == ["route_networks.txt"]


def test_the_column_alone_is_not_a_conflict():
    tables = {"routes.txt": [{"route_id": "R1", "network_id": "N1"}]}
    assert fire_file(CODE, tables) == []


def test_a_declared_but_empty_column_still_conflicts():
    # hasColumn is a header test, so a routes.txt whose network_id is blank on every
    # row still conflicts with a networks.txt.
    tables = {
        "routes.txt": [{"route_id": "R1", "network_id": None}],
        "networks.txt": [{"network_id": "N1"}],
    }
    assert [n.context["fileNameB"] for n in fire_file(CODE, tables)] == ["networks.txt"]


def test_no_network_id_column_means_no_conflict():
    tables = {"routes.txt": [{"route_id": "R1"}], "networks.txt": [{"network_id": "N1"}]}
    assert fire_file(CODE, tables) == []


def media(media_id, name, media_type, row_number):
    return {
        "fare_media_id": media_id,
        "fare_media_name": name,
        "fare_media_type": media_type,
        "_row_number": row_number,
    }


def test_duplicate_fare_media_keys_on_name_and_type():
    # Measured on A/B/C/D/E/F. putIfAbsent keeps the first row per key, so F, a third
    # copy of A's key, names A rather than B. A blank name groups rather than being
    # skipped, and the same name with a different type is not a duplicate.
    tables = {
        "fare_media.txt": [
            media("A", "Card", 2, 2),
            media("B", "Card", 2, 3),
            media("C", "Card", 3, 4),
            media("D", None, 2, 5),
            media("E", None, 2, 6),
            media("F", "Card", 2, 7),
        ]
    }
    assert [n.context for n in fire_file("duplicate_fare_media", tables)] == [
        {"csvRowNumber1": 2, "fareMediaId1": "A", "csvRowNumber2": 3, "fareMediaId2": "B"},
        {"csvRowNumber1": 5, "fareMediaId1": "D", "csvRowNumber2": 6, "fareMediaId2": "E"},
        {"csvRowNumber1": 2, "fareMediaId1": "A", "csvRowNumber2": 7, "fareMediaId2": "F"},
    ]


def test_distinct_fare_media_draw_nothing():
    tables = {"fare_media.txt": [media("A", "Card", 2, 2), media("B", "Ticket", 1, 3)]}
    assert fire_file("duplicate_fare_media", tables) == []


def test_a_card_or_app_medium_without_a_name_is_reported():
    # The rule-layer half of missing_recommended_field: fare_media_name is
    # unannotated upstream, so the engine never emits this and FareMediaNameValidator
    # is the only source. Measured: blank-name rows of type 2 are both reported.
    for media_type in (2, 4):
        row = {"fare_media_name": None, "fare_media_type": media_type, "_row_number": 5}
        assert [
            n.context for n in fire_file("missing_recommended_field", {"fare_media.txt": [row]})
        ] == [
            {
                "filename": "fare_media.txt",
                "csvRowNumber": 5,
                "fieldName": "fare_media_name",
            }
        ], media_type


def test_other_media_types_do_not_need_a_name():
    # NONE, PAPER_TICKET and CONTACTLESS_EMV fall through to false upstream, as does
    # an unrecognised value via the switch default.
    for media_type in (0, 1, 3, -1, None):
        row = {"fare_media_name": None, "fare_media_type": media_type, "_row_number": 5}
        assert fire_file("missing_recommended_field", {"fare_media.txt": [row]}) == [], media_type


def test_a_named_medium_is_not_reported():
    row = {"fare_media_name": "Card", "fare_media_type": 2, "_row_number": 5}
    assert fire_file("missing_recommended_field", {"fare_media.txt": [row]}) == []


def transfer(row_number, transfer_type, from_stop=None, to_stop=None):
    return {
        "_row_number": row_number,
        "transfer_type": transfer_type,
        "from_stop_id": from_stop,
        "to_stop_id": to_stop,
    }


def test_a_transfer_missing_both_stop_ids_reports_both():
    # Measured on nullkeyfeed: two rows of transfer_type 0 with both ids blank draw
    # four notices. Both fields are ConditionallyRequired upstream, so the engine
    # emits nothing for them and this validator is the only source.
    tables = {"transfers.txt": [transfer(2, 0), transfer(3, 0)]}
    assert [
        (n.context["csvRowNumber"], n.context["fieldName"])
        for n in fire_file("missing_required_field", tables)
    ] == [
        (2, "from_stop_id"),
        (2, "to_stop_id"),
        (3, "from_stop_id"),
        (3, "to_stop_id"),
    ]


def test_an_in_seat_transfer_needs_the_trip_ids_instead_of_the_stop_ids():
    """Types 4 and 5 imply their stops from the trips, and therefore *require* the trips.

    This test used to assert that such a transfer draws nothing at all, which was true of the
    stop-id branch alone and false of the jar: it reports both trip ids as missing. The gap survived
    several cohorts and was found by a probe built for a different rule.
    """
    for transfer_type in (4, 5):
        tables = {"transfers.txt": [transfer(2, transfer_type)]}
        got = fire_file("missing_required_field", tables)
        assert [(n.context["csvRowNumber"], n.context["fieldName"]) for n in got] == [
            (2, "from_trip_id"),
            (2, "to_trip_id"),
        ], transfer_type
    # Supplying both trips satisfies it, and the stop ids are still not wanted.
    complete = {
        "transfers.txt": [
            dict(transfer(2, 4), from_trip_id="T1", to_trip_id="T2"),
        ]
    }
    assert fire_file("missing_required_field", complete) == []


def test_a_transfer_without_a_type_is_skipped_entirely():
    # hasTransferType, so a blank type is skipped rather than read as 0.
    tables = {"transfers.txt": [transfer(2, None)]}
    assert fire_file("missing_required_field", tables) == []


def test_a_complete_transfer_draws_nothing():
    tables = {"transfers.txt": [transfer(2, 0, "S1", "S2")]}
    assert fire_file("missing_required_field", tables) == []


def shape_point(shape_id, row_number):
    return {"shape_id": shape_id, "_row_number": row_number}


def test_only_single_point_shapes_are_reported():
    # Measured: one single-point shape, one three-point shape and a second
    # single-point shape draw two notices, for the two singletons.
    tables = {
        "shapes.txt": [
            shape_point("SH_ONE", 2),
            shape_point("SH_MANY", 3),
            shape_point("SH_MANY", 4),
            shape_point("SH_MANY", 5),
            shape_point("SH_ALSO", 6),
        ]
    }
    assert [n.context for n in fire_file("single_shape_point", tables)] == [
        {"shapeId": "SH_ONE", "csvRowNumber": 2},
        {"shapeId": "SH_ALSO", "csvRowNumber": 6},
    ]


def test_a_two_point_shape_is_enough():
    tables = {"shapes.txt": [shape_point("SH", 2), shape_point("SH", 3)]}
    assert fire_file("single_shape_point", tables) == []


def test_no_shapes_file_reports_nothing():
    assert fire_file("single_shape_point", {}) == []


def test_only_unreferenced_shapes_are_reported_once_each():
    # Measured on the same shapes.txt as single_shape_point, with a trip on SH_MANY:
    # two notices, at the first row of each unreferenced shape.
    tables = {
        "trips.txt": [{"shape_id": "SH_MANY"}],
        "shapes.txt": [
            shape_point("SH_ONE", 2),
            shape_point("SH_MANY", 3),
            shape_point("SH_MANY", 4),
            shape_point("SH_MANY", 5),
            shape_point("SH_ALSO", 6),
        ],
    }
    assert [n.context for n in fire_file("unused_shape", tables)] == [
        {"shapeId": "SH_ONE", "csvRowNumber": 2},
        {"shapeId": "SH_ALSO", "csvRowNumber": 6},
    ]


def test_a_multi_point_unused_shape_is_reported_once_at_its_first_row():
    # reportedShapes.add guards the check, so fifty points draw one notice naming the
    # first row rather than fifty, or the last.
    tables = {
        "trips.txt": [],
        "shapes.txt": [shape_point("SH", row) for row in (2, 3, 4)],
    }
    assert [n.context for n in fire_file("unused_shape", tables)] == [
        {"shapeId": "SH", "csvRowNumber": 2}
    ]


def test_a_shape_used_by_any_trip_is_not_reported():
    tables = {
        "trips.txt": [{"shape_id": "SH"}],
        "shapes.txt": [shape_point("SH", 2)],
    }
    assert fire_file("unused_shape", tables) == []


def stop_row(stop_id, name, location_type, row_number, parent=None):
    return {
        "stop_id": stop_id,
        "stop_name": name,
        "location_type": location_type,
        "parent_station": parent,
        "_row_number": row_number,
    }


def test_a_station_with_only_an_entrance_is_still_unused():
    # The boundary worth measuring: only a location_type 0 child excuses a station.
    # Measured: a station whose sole child is an entrance is reported, as is one with
    # no children, while one with a platform is not.
    tables = {
        "stops.txt": [
            stop_row("ST_STOP", "Station With Stop", 1, 2),
            stop_row("P1", "Platform One", 0, 3, parent="ST_STOP"),
            stop_row("ST_ENT", "Station With Entrance", 1, 4),
            stop_row("E1", "Entrance One", 2, 5, parent="ST_ENT"),
            stop_row("ST_NONE", "Lonely Station", 1, 6),
        ]
    }
    assert [n.context for n in fire_file("unused_station", tables)] == [
        {"csvRowNumber": 4, "stopId": "ST_ENT", "stopName": "Station With Entrance"},
        {"csvRowNumber": 6, "stopId": "ST_NONE", "stopName": "Lonely Station"},
    ]


def test_a_child_with_a_blank_location_type_counts_as_a_stop():
    # location_type is optional and defaults to 0.
    tables = {
        "stops.txt": [
            stop_row("ST", "Station", 1, 2),
            stop_row("P1", "Platform", None, 3, parent="ST"),
        ]
    }
    assert fire_file("unused_station", tables) == []


def test_a_feed_with_no_stations_reports_nothing():
    tables = {"stops.txt": [stop_row("S1", "Stop", 0, 2)]}
    assert fire_file("unused_station", tables) == []


def test_a_station_with_a_blank_name_reports_an_empty_string():
    # Not a dropped key: the generated entity returns the String default, so the jar
    # reports "". Caught by the differential on a feed built for another rule, and it
    # is the same shape as attribution_without_role's attributionId.
    tables = {"stops.txt": [stop_row("ST", None, 1, 4)]}
    assert [n.context for n in fire_file("unused_station", tables)] == [
        {"csvRowNumber": 4, "stopId": "ST", "stopName": ""}
    ]


def test_a_trip_with_fewer_than_two_stop_times_is_unusable():
    # The threshold is <= 1, not == 0: one stop time is not a journey.
    tables = {
        "trips.txt": [
            {"trip_id": "T_none", "_row_number": 2},
            {"trip_id": "T_one", "_row_number": 3},
            {"trip_id": "T_two", "_row_number": 4},
        ],
        "stop_times.txt": [
            {"trip_id": "T_one"},
            {"trip_id": "T_two"},
            {"trip_id": "T_two"},
        ],
    }
    assert [n.context for n in fire_file("unusable_trip", tables)] == [
        {"csvRowNumber": 2, "tripId": "T_none"},
        {"csvRowNumber": 3, "tripId": "T_one"},
    ]


def test_a_feed_with_no_trips_reports_no_unusable_trip():
    assert fire_file("unusable_trip", {"stop_times.txt": [{"trip_id": "T"}]}) == []


def test_a_pathway_from_a_stop_to_itself_is_a_loop():
    notices = fire(
        "pathway_loop",
        {"pathway_id": "P1", "from_stop_id": "S1", "to_stop_id": "S1", "_row_number": 2},
    )
    assert [n.context for n in notices] == [{"csvRowNumber": 2, "pathwayId": "P1", "stopId": "S1"}]


def test_a_pathway_between_two_stops_is_not_a_loop():
    assert (
        fire(
            "pathway_loop",
            {"pathway_id": "P1", "from_stop_id": "S1", "to_stop_id": "S2", "_row_number": 2},
        )
        == []
    )


def test_a_pathway_missing_an_end_is_not_a_loop():
    # Both ends must be present as well as equal, so a half-specified pathway is
    # another rule's problem rather than a loop.
    for from_stop, to_stop in ((None, None), ("S1", None), (None, "S1")):
        row = {
            "pathway_id": "P1",
            "from_stop_id": from_stop,
            "to_stop_id": to_stop,
            "_row_number": 2,
        }
        assert fire("pathway_loop", row) == [], (from_stop, to_stop)


def platform(stop_id, name, row_number, level=None):
    return {"stop_id": stop_id, "stop_name": name, "level_id": level, "_row_number": row_number}


def test_only_elevator_endpoints_without_a_level_are_reported():
    # Measured: an elevator between a platform with a level and one without reports
    # only the one without, and a walkway endpoint with no level is untouched.
    tables = {
        "pathways.txt": [
            {"pathway_id": "P1", "from_stop_id": "A", "to_stop_id": "B", "pathway_mode": 5},
            {"pathway_id": "P2", "from_stop_id": "A", "to_stop_id": "C", "pathway_mode": 1},
        ],
        "stops.txt": [
            platform("A", "Platform A", 3, level="L1"),
            platform("B", "Platform B", 4),
            platform("C", "Platform C", 5),
        ],
    }
    assert [n.context for n in fire_file("missing_level_id", tables)] == [
        {"csvRowNumber": 4, "stopId": "B", "stopName": "Platform B"}
    ]


def test_a_feed_with_no_elevator_reports_nothing():
    tables = {
        "pathways.txt": [
            {"pathway_id": "P1", "from_stop_id": "A", "to_stop_id": "B", "pathway_mode": 1}
        ],
        "stops.txt": [platform("A", "A", 2), platform("B", "B", 3)],
    }
    assert fire_file("missing_level_id", tables) == []


def test_an_endpoint_missing_from_stops_is_skipped():
    # The broken reference is another rule's to report.
    tables = {
        "pathways.txt": [
            {"pathway_id": "P1", "from_stop_id": "GONE", "to_stop_id": "B", "pathway_mode": 5}
        ],
        "stops.txt": [platform("B", "B", 3, level="L1")],
    }
    assert fire_file("missing_level_id", tables) == []


def stop_time(trip_id, seq, row_number, arrival=None, departure=None, window=None):
    return {
        "trip_id": trip_id,
        "stop_sequence": seq,
        "arrival_time": arrival,
        "departure_time": departure,
        "start_pickup_drop_off_window": window,
        "end_pickup_drop_off_window": None,
        "_row_number": row_number,
    }


def test_trip_edges_are_by_stop_sequence_not_file_order():
    # Measured on rows appearing as sequence 3, 1, 2: the notices name sequence 1 on
    # row 3 and sequence 3 on row 2. Reading file order would blame the wrong rows,
    # and the interior stop with neither time is correctly ignored.
    tables = {
        "stop_times.txt": [
            stop_time("T1", 3, 2, arrival=30000),
            stop_time("T1", 1, 3, departure=28800),
            stop_time("T1", 2, 4),
        ]
    }
    assert [n.context for n in fire_file("missing_trip_edge", tables)] == [
        {
            "csvRowNumber": 3,
            "stopSequence": 1,
            "tripId": "T1",
            "specifiedField": "arrival_time",
        },
        {
            "csvRowNumber": 2,
            "stopSequence": 3,
            "tripId": "T1",
            "specifiedField": "departure_time",
        },
    ]


def test_complete_edges_draw_nothing():
    tables = {
        "stop_times.txt": [
            stop_time("T2", 1, 2, arrival=32400, departure=32400),
            stop_time("T2", 2, 3, arrival=33000, departure=33000),
        ]
    }
    assert fire_file("missing_trip_edge", tables) == []


def test_an_edge_with_a_pickup_window_is_exempt():
    # A demand-responsive stop carries a window instead of a timetable.
    tables = {
        "stop_times.txt": [
            stop_time("T3", 1, 2, window=28800),
            stop_time("T3", 2, 3, arrival=33000, departure=33000),
        ]
    }
    assert fire_file("missing_trip_edge", tables) == []


SDT_COLUMNS = {
    "stop_times.txt": [{"shape_dist_traveled": None, "location_group_id": None, "stop_id": None}]
}


def sdt_row(row_number, stop=None, group=None, location=None, distance=None):
    return {
        "trip_id": "T1",
        "stop_id": stop,
        "location_group_id": group,
        "location_id": location,
        "shape_dist_traveled": distance,
        "_row_number": row_number,
    }


def test_a_distance_on_a_location_group_is_forbidden():
    # Measured: the row naming a location group and a distance is reported with
    # locationId "" rather than a dropped key, while a normal stop carrying a
    # distance and a location group without one are both fine.
    tables = {
        "stop_times.txt": [
            sdt_row(2, stop="S1", distance=1.5),
            sdt_row(3, group="LG1", distance=2.5),
            sdt_row(4, group="LG1"),
        ]
    }
    assert [n.context for n in fire_file("forbidden_shape_dist_traveled", tables)] == [
        {
            "csvRowNumber": 3,
            "tripId": "T1",
            "locationGroupId": "LG1",
            "locationId": "",
            "shapeDistTraveled": 2.5,
        }
    ]


def test_the_rule_needs_both_header_conditions():
    # shouldCallValidate is an AND: shape_dist_traveled plus one of the zone columns.
    # A stop_times.txt declaring neither zone column runs nothing.
    tables = {"stop_times.txt": [{"shape_dist_traveled": 2.5, "stop_id": None, "_row_number": 2}]}
    assert fire_file("forbidden_shape_dist_traveled", tables) == []


def geo_row(row_number, stop=None, group=None, location=None):
    return {
        "stop_id": stop,
        "location_group_id": group,
        "location_id": location,
        "_row_number": row_number,
    }


def test_two_geography_ids_are_forbidden_and_the_absent_one_is_omitted():
    # Upstream passes an explicit null for each id it lacks and gson drops it, so this
    # differs from the four notices where the String default shows through as "".
    # Measured: no locationId key at all.
    notices = fire("forbidden_geography_id", geo_row(3, stop="S2", group="LG1"))
    assert [n.context for n in notices] == [
        {"csvRowNumber": 3, "stopId": "S2", "locationGroupId": "LG1"}
    ]


def test_exactly_one_geography_id_is_fine():
    for kwargs in ({"stop": "S1"}, {"group": "LG1"}, {"location": "L1"}):
        assert fire("forbidden_geography_id", geo_row(2, **kwargs)) == [], kwargs


def test_no_geography_id_is_another_rules_problem():
    # The zero case draws missing_required_field, not this notice.
    assert fire("forbidden_geography_id", geo_row(2)) == []


def test_all_three_geography_ids_are_reported_together():
    notices = fire("forbidden_geography_id", geo_row(4, stop="S1", group="LG1", location="L1"))
    assert [n.context for n in notices] == [
        {
            "csvRowNumber": 4,
            "stopId": "S1",
            "locationGroupId": "LG1",
            "locationId": "L1",
        }
    ]


def test_a_stop_time_naming_no_geography_reports_stop_id():
    # The zero case of StopTimesGeographyIdPresenceValidator, which shares the
    # missing_required_field module with the transfers validator: one module per code,
    # whatever the number of upstream sources. Measured on the same probe.
    tables = {
        "stop_times.txt": [
            {"stop_id": "S1", "location_group_id": None, "location_id": None, "_row_number": 2},
            {"stop_id": None, "location_group_id": None, "location_id": None, "_row_number": 4},
        ]
    }
    reported = [
        n.context
        for n in fire_file("missing_required_field", tables)
        if n.context["filename"] == "stop_times.txt"
    ]
    assert reported == [{"filename": "stop_times.txt", "csvRowNumber": 4, "fieldName": "stop_id"}]


def tp_row(row_number, seq, arrival=None, departure=None, timepoint=None):
    return {
        "trip_id": "T1",
        "stop_sequence": seq,
        "arrival_time": arrival,
        "departure_time": departure,
        "timepoint": timepoint,
        "_row_number": row_number,
    }


TP_TABLE = {
    "stop_times.txt": [
        tp_row(2, 1, arrival=28800, departure=28800),
        tp_row(3, 2, timepoint=1),
        tp_row(4, 3, arrival=30000, departure=30000, timepoint=0),
        tp_row(5, 4, arrival=30600, departure=30600, timepoint=1),
    ]
}


def test_a_timed_stop_without_a_timepoint_value_is_reported():
    # Measured: only the row with times and no timepoint. A timepoint of 0 with times
    # is fine, so the check is on the field's presence rather than its value.
    assert [n.context for n in fire_file("missing_timepoint_value", TP_TABLE)] == [
        {"csvRowNumber": 2, "tripId": "T1", "stopSequence": 1}
    ]


def test_an_exact_timepoint_without_times_reports_both_fields():
    assert [n.context for n in fire_file("stop_time_timepoint_without_times", TP_TABLE)] == [
        {"csvRowNumber": 3, "tripId": "T1", "stopSequence": 2, "specifiedField": "arrival_time"},
        {"csvRowNumber": 3, "tripId": "T1", "stopSequence": 2, "specifiedField": "departure_time"},
    ]


def test_neither_timepoint_rule_runs_without_the_column():
    # Legacy feeds omit timepoint entirely, and upstream deliberately says nothing
    # about their missing times: that is the header tests' business.
    tables = {"stop_times.txt": [{"trip_id": "T1", "stop_sequence": 1, "_row_number": 2}]}
    assert fire_file("missing_timepoint_value", tables) == []
    assert fire_file("stop_time_timepoint_without_times", tables) == []


def window_row(row_number, pickup=None, drop_off=None, start=None, end=None):
    return {
        "pickup_type": pickup,
        "drop_off_type": drop_off,
        "start_pickup_drop_off_window": start,
        "end_pickup_drop_off_window": end,
        "_row_number": row_number,
    }


def test_an_absent_window_renders_as_zero_rather_than_being_omitted():
    # GtfsTime's default is zero and its adapter formats it, so an absent end window
    # is "00:00:00". Measured. That is a third answer for an absent value, after the
    # String default's "" and gson dropping an explicit null.
    notices = fire("forbidden_pickup_type", window_row(3, pickup=0, drop_off=0, start=32400))
    assert [n.context for n in notices] == [
        {
            "csvRowNumber": 3,
            "startPickupDropOffWindow": "09:00:00",
            "endPickupDropOffWindow": "00:00:00",
        }
    ]


def test_the_pickup_branch_is_wider_than_the_drop_off_branch():
    # Measured: pickup rejects REGULAR and ON_REQUEST_TO_DRIVER, drop-off only
    # REGULAR. The asymmetry is upstream's.
    on_request = window_row(5, pickup=3, drop_off=1, start=39600, end=41400)
    assert len(fire("forbidden_pickup_type", on_request)) == 1
    assert fire("forbidden_drop_off_type", on_request) == []


def test_a_phone_agency_pickup_with_a_window_is_fine():
    row = window_row(4, pickup=2, drop_off=1, start=36000, end=37800)
    assert fire("forbidden_pickup_type", row) == []
    assert fire("forbidden_drop_off_type", row) == []


def test_a_row_without_a_window_is_ignored():
    row = window_row(2, pickup=0, drop_off=0)
    assert fire("forbidden_pickup_type", row) == []
    assert fire("forbidden_drop_off_type", row) == []


def tc_row(row_number, from_group="L1", to_group="L1", count=None):
    return {
        "from_leg_group_id": from_group,
        "to_leg_group_id": to_group,
        "transfer_count": count,
        "_row_number": row_number,
    }


def test_a_self_transfer_count_range_is_below_minus_one_or_zero():
    # Measured: 0 and -2 are invalid, -1 (unlimited) and 3 are not. Not a simple
    # lower bound, since -1 is valid and 0 is not.
    for count, invalid in ((0, True), (-2, True), (-1, False), (3, False)):
        notices = fire("fare_transfer_rule_invalid_transfer_count", tc_row(2, count=count))
        assert bool(notices) is invalid, count
        if invalid:
            assert notices[0].context == {"csvRowNumber": 2, "transferCount": count}


def test_a_self_transfer_needs_a_count():
    assert [n.context for n in fire("fare_transfer_rule_without_transfer_count", tc_row(6))] == [
        {"csvRowNumber": 6}
    ]


def test_a_cross_group_transfer_must_not_have_a_count():
    row = tc_row(7, to_group="L2", count=2)
    assert [n.context for n in fire("fare_transfer_rule_with_forbidden_transfer_count", row)] == [
        {"csvRowNumber": 7}
    ]
    # And the other two branches stay quiet for it.
    assert fire("fare_transfer_rule_invalid_transfer_count", row) == []
    assert fire("fare_transfer_rule_without_transfer_count", row) == []


def test_a_cross_group_transfer_without_a_count_is_fine():
    row = tc_row(8, to_group="L2")
    for code in (
        "fare_transfer_rule_invalid_transfer_count",
        "fare_transfer_rule_without_transfer_count",
        "fare_transfer_rule_with_forbidden_transfer_count",
    ):
        assert fire(code, row) == [], code


def test_a_missing_leg_group_is_not_a_self_transfer():
    # Objects.equals is guarded by both being present, so a rule missing one end is
    # treated as a cross-group transfer.
    row = tc_row(9, to_group=None, count=2)
    assert len(fire("fare_transfer_rule_with_forbidden_transfer_count", row)) == 1


def test_location_type_single_entity_branches():
    """Measured on acfeed: three location types need a parent, a station may not
    have one, and a platform_code without a parent is an INFO."""
    stops = [
        {
            "_row_number": 2,
            "stop_id": "ST1",
            "stop_name": "Station One",
            "location_type": 1,
            "parent_station": "ST2",
        },
        {"_row_number": 3, "stop_id": "ST2", "stop_name": "Station Two", "location_type": 1},
        {
            "_row_number": 4,
            "stop_id": "P1",
            "stop_name": "Platform One",
            "location_type": 0,
            "platform_code": "A",
        },
        {
            "_row_number": 5,
            "stop_id": "P2",
            "stop_name": "Platform Two",
            "location_type": 0,
            "parent_station": "ST2",
            "platform_code": "B",
        },
        {"_row_number": 6, "stop_id": "E1", "stop_name": "Entrance One", "location_type": 2},
        {"_row_number": 7, "stop_id": "G1", "stop_name": "Node One", "location_type": 3},
        {"_row_number": 8, "stop_id": "B1", "stop_name": "Boarding One", "location_type": 4},
        {"_row_number": 9, "stop_id": "S9", "stop_name": "Plain Stop"},
    ]
    from gtfs_validator.rules import (
        location_without_parent_station,
        platform_without_parent_station,
        station_with_parent_station,
    )

    ctx = CTX
    got = [n for row in stops for n in station_with_parent_station.check(row, ctx)]
    assert [(n.context["csvRowNumber"], n.context["parentStation"]) for n in got] == [(2, "ST2")]
    assert got[0].context == {
        "csvRowNumber": 2,
        "stopId": "ST1",
        "stopName": "Station One",
        "parentStation": "ST2",
    }

    got = [n for row in stops for n in platform_without_parent_station.check(row, ctx)]
    assert [n.context for n in got] == [
        {"csvRowNumber": 4, "stopId": "P1", "stopName": "Platform One"}
    ]
    assert got[0].severity is Severity.INFO

    got = [n for row in stops for n in location_without_parent_station.check(row, ctx)]
    assert [(n.context["csvRowNumber"], n.context["locationType"]) for n in got] == [
        (6, 2),
        (7, 3),
        (8, 4),
    ]


def test_agency_consistency_lang_reports_language_subtag_only():
    """Measured: en-US against en draws a notice whose expected and actual are both
    "en", because Locale.equals is region-sensitive but the notice carries
    Locale.getLanguage(). EN against en draws nothing: the tag is canonicalised."""
    from gtfs_validator.rules import inconsistent_agency_lang

    def langs(*values):
        rows = [
            {
                "_row_number": index + 2,
                "agency_id": f"A{index}",
                "agency_name": "N",
                "agency_lang": value,
                "agency_timezone": "America/New_York",
            }
            for index, value in enumerate(values)
        ]
        feed = FakeFeed({"agency.txt": rows})
        return [
            (n.context["csvRowNumber"], n.context["expected"], n.context["actual"])
            for n in inconsistent_agency_lang.check(feed, CTX)
        ]

    assert langs("en", "en-us") == [(3, "en", "en")]
    assert langs("en", "EN") == []
    assert langs("fr", "he", "id", "yi", "zh-Hant-TW") == [
        (3, "fr", "he"),
        (4, "fr", "id"),
        (5, "fr", "yi"),
        (6, "fr", "zh"),
    ]
    # An absent lang is skipped, and does not become the common language.
    assert langs(None, "fr", "de") == [(4, "fr", "de")]
    # One agency cannot mismatch itself.
    assert langs("en") == []


def test_agency_consistency_timezone_and_missing_id():
    """Measured on acfeed: the first agency's timezone is the expected one, and a
    blank agency_id is required rather than recommended once there are two agencies."""
    from gtfs_validator.rules import inconsistent_agency_timezone, missing_required_agency_id

    rows = [
        {
            "_row_number": 2,
            "agency_id": "A1",
            "agency_name": "Alpha",
            "agency_timezone": "America/New_York",
        },
        {
            "_row_number": 3,
            "agency_id": "A2",
            "agency_name": "Beta",
            "agency_timezone": "America/Chicago",
        },
        {"_row_number": 4, "agency_name": "Gamma", "agency_timezone": "America/New_York"},
    ]
    feed = FakeFeed({"agency.txt": rows})
    assert [n.context for n in inconsistent_agency_timezone.check(feed, CTX)] == [
        {"csvRowNumber": 3, "expected": "America/New_York", "actual": "America/Chicago"}
    ]
    assert [n.context for n in missing_required_agency_id.check(feed, CTX)] == [
        {"filename": "agency.txt", "csvRowNumber": 4, "agencyName": "Gamma"}
    ]
    # A lone agency without an id is recommended-only, so this rule stays quiet.
    lone = FakeFeed({"agency.txt": [{"_row_number": 2, "agency_name": "Solo"}]})
    assert list(missing_required_agency_id.check(lone, CTX)) == []
    assert list(inconsistent_agency_timezone.check(lone, CTX)) == []


def test_missing_recommended_field_covers_the_lone_agency_id():
    """AgencyConsistencyValidator's single-agency branch: agency_id is recommended
    when it is the only agency, and required as soon as there are two."""
    from gtfs_validator.rules import missing_recommended_field

    lone = FakeFeed({"agency.txt": [{"_row_number": 2, "agency_name": "Solo"}]})
    got = [n.context for n in missing_recommended_field.check(lone, CTX)]
    assert {"filename": "agency.txt", "csvRowNumber": 2, "fieldName": "agency_id"} in got
    two = FakeFeed(
        {
            "agency.txt": [
                {"_row_number": 2, "agency_name": "Solo"},
                {"_row_number": 3, "agency_id": "A2", "agency_name": "Other"},
            ]
        }
    )
    assert [
        n.context
        for n in missing_recommended_field.check(two, CTX)
        if n.context.get("fieldName") == "agency_id"
    ] == []


def test_fare_media_half_survives_a_table_that_failed_to_load():
    """Measured on a fare_media.txt whose first row wants a name and whose second has an
    unparsable fare_media_type: the jar reports the notice for the clean row, because a
    SingleEntityValidator runs per row during loading. Reading through the gated rows()
    lost it, which is the whole reason entity_rows() exists.
    """
    from gtfs_validator.rules import missing_recommended_field

    tables = {
        "fare_media.txt": [
            {"_row_number": 2, "fare_media_id": "M1", "fare_media_name": None, "fare_media_type": 2}
        ]
    }
    feed = FakeFeed(tables, unindexable=frozenset({"fare_media.txt"}))
    assert [n.context for n in missing_recommended_field.check(feed, CTX)] == [
        {"filename": "fare_media.txt", "csvRowNumber": 2, "fieldName": "fare_media_name"}
    ]


def test_locale_canonicalisation_matches_the_oracled_table():
    """Each pair oracled from the pinned JDK. The first three contradicted a plain
    reading of the Builder's javadoc, and each was a live divergence."""
    from gtfs_validator.rules._shared import locales

    same = [
        ("en", "EN"),
        ("en-US", "en-us"),
        ("i-klingon", "tlh"),
        ("no-bok", "nb"),
        ("art-lojban", "jbo"),
        ("en-u-ca-buddhist-nu-thai", "en-u-nu-thai-ca-buddhist"),
    ]
    for left, right in same:
        assert locales.canonical(left) == locales.canonical(right), (left, right)
    different = [("en", "en-US"), ("en-US-posix", "en-US-POSIX"), ("und", "en")]
    for left, right in different:
        assert locales.canonical(left) != locales.canonical(right), (left, right)
    assert locales.language_of("und") == ""
    assert locales.language_of("i-klingon") == "tlh"
    assert locales.language_of("zh-Hant-TW") == "zh"
    assert locales.language_of("en-GB-oed") == "en"
    # No legacy ISO remapping: measured as themselves, not iw, in and ji.
    assert [locales.language_of(tag) for tag in ("he", "id", "yi")] == ["he", "id", "yi"]


def test_the_capped_sample_order_of_the_hash_iterating_rules():
    """Above 1,000 notices of one code the iteration order decides which are kept.

    Four rules were audited against feeds carrying 1,005 findings each. Two iterate a hash
    collection upstream and needed `javahash`; two already matched file order and were left
    alone, which is the part that stops this being a blanket change:

    | Rule | Jar's first samples | Order |
    |---|---|---|
    | single_shape_point | SH0809, SH0808, SH0807 | HashMap |
    | unused_station | ST0160, ST0161, ST0162 | HashSet |
    | unused_shape | SH0000, SH0001, SH0002 | file |
    | expired_calendar | EX0000, EX0001, EX0002 | file |
    """
    from gtfs_validator.javahash import hashmap_order

    shapes = {f"SH{index:04d}": 1 for index in range(1005)}
    rows = {shape_id: number + 2 for number, shape_id in enumerate(shapes)}
    got = fire_file(
        "single_shape_point",
        {
            "shapes.txt": [
                {
                    "_row_number": rows[shape_id],
                    "shape_id": shape_id,
                    "shape_pt_lat": 40.0,
                    "shape_pt_lon": -74.0,
                    "shape_pt_sequence": 1,
                }
                for shape_id in shapes
            ]
        },
    )
    assert [notice.context["shapeId"] for notice in got][:3] == ["SH0809", "SH0808", "SH0807"]
    assert [notice.context["shapeId"] for notice in got] == hashmap_order(shapes)

    stations = [
        {
            "_row_number": index + 2,
            "stop_id": f"ST{index:04d}",
            "stop_name": f"Station {index}",
            "location_type": 1,
        }
        for index in range(1005)
    ]
    got = fire_file("unused_station", {"stops.txt": stations})
    assert [notice.context["stopId"] for notice in got][:3] == ["ST0160", "ST0161", "ST0162"]


def test_the_feed_language_is_compared_as_a_full_locale_but_reported_as_a_tag():
    """Measured on `lang_feed`. en-US against a feed declaring en is a mismatch, because the
    comparison is Locale.equals, and it is reported as "en-US" against "en", because the notice
    carries toLanguageTag(). The sibling rule inconsistent_agency_lang reports getLanguage() for the
    same pair and would say "en" against "en".
    """
    tables = {
        "feed_info.txt": [{"_row_number": 2, "feed_publisher_name": "Pub", "feed_lang": "en"}],
        "agency.txt": [
            {"_row_number": 2, "agency_id": "A1", "agency_name": "Alpha", "agency_lang": "en"},
            {"_row_number": 3, "agency_id": "A2", "agency_name": "Beta", "agency_lang": "fr"},
            {"_row_number": 4, "agency_id": "A3", "agency_name": "Gamma", "agency_lang": "en-US"},
            {"_row_number": 5, "agency_id": "A4", "agency_name": "Delta", "agency_lang": None},
        ],
    }
    got = [n.context for n in fire_file("feed_info_lang_and_agency_lang_mismatch", tables)]
    assert got == [
        {
            "csvRowNumber": 3,
            "agencyId": "A2",
            "agencyName": "Beta",
            "agencyLang": "fr",
            "feedLang": "en",
        },
        {
            "csvRowNumber": 4,
            "agencyId": "A3",
            "agencyName": "Gamma",
            "agencyLang": "en-US",
            "feedLang": "en",
        },
    ]


def test_a_multilingual_feed_skips_the_language_comparison():
    """`mul` is the ISO code for multiple languages, and it silences the check for every agency at
    once. Measured on `lang_mul`, where the jar reports nothing despite an agency declaring fr."""
    tables = {
        "feed_info.txt": [{"_row_number": 2, "feed_publisher_name": "Pub", "feed_lang": "mul"}],
        "agency.txt": [
            {"_row_number": 3, "agency_id": "A2", "agency_name": "Beta", "agency_lang": "fr"}
        ],
    }
    assert fire_file("feed_info_lang_and_agency_lang_mismatch", tables) == []


def test_two_default_rider_categories_report_the_first_pair():
    """Measured on `fare_default` and `fare_three`: three defaults still draw one notice naming the
    first two in file order, the same category listed twice does not count twice, and a category
    that is not marked default does not count at all.
    """
    tables = {
        "rider_categories.txt": [
            {"_row_number": 2, "rider_category_id": "RC1", "is_default_fare_category": 1},
            {"_row_number": 3, "rider_category_id": "RC2", "is_default_fare_category": 1},
            {"_row_number": 4, "rider_category_id": "RC3", "is_default_fare_category": 0},
        ],
        "fare_products.txt": [
            {"_row_number": 2, "fare_product_id": "FP1", "rider_category_id": "RC1"},
            {"_row_number": 3, "fare_product_id": "FP1", "rider_category_id": "RC2"},
            {"_row_number": 4, "fare_product_id": "FP1", "rider_category_id": "RC3"},
            {"_row_number": 5, "fare_product_id": "FP2", "rider_category_id": "RC1"},
            {"_row_number": 6, "fare_product_id": "FP2", "rider_category_id": "RC1"},
        ],
    }
    got = [
        n.context for n in fire_file("fare_product_with_multiple_default_rider_categories", tables)
    ]
    assert got == [
        {
            "fareProductId": "FP1",
            "csvRowNumber1": 2,
            "riderCategoryId1": "RC1",
            "csvRowNumber2": 3,
            "riderCategoryId2": "RC2",
        }
    ]
    # Gated on rider_categories.txt existing at all.
    assert (
        fire_file(
            "fare_product_with_multiple_default_rider_categories",
            {"fare_products.txt": tables["fare_products.txt"]},
        )
        == []
    )


def test_the_locale_helper_matches_to_language_tag_on_the_awkward_tags():
    """Oracled from the JDK on 31 tags.

    The first pass used 17 and reported zero mismatches, which was true of that corpus and not of
    Java: a review found `und-x-private` and `zh-cmn`, and both were wrong. An extlang replaces the
    language, `und` disappears when only private use follows it, and everything after `x-` belongs
    to the private-use section however short each subtag is.
    """
    from gtfs_validator.rules._shared.locales import canonical, language_of, language_tag

    assert language_tag("zh-cmn") == "cmn"
    assert language_tag("zh-cmn-Hant-TW") == "cmn-Hant-TW"
    assert language_tag("und-x-private") == "x-private"
    assert language_tag("und-x-a-b") == "x-a-b"
    assert language_tag("und-US") == "und-US"
    assert language_tag("und") == "und"
    assert language_of("zh-cmn") == "cmn"
    assert language_of("und-x-private") == ""
    # Equality follows the same canonicalisation, so these are not mismatches.
    assert canonical("und-x-private") == canonical("x-private")
    assert canonical("zh-cmn") == canonical("cmn")
    assert canonical("und") != canonical("x-private")


def test_a_duplicate_rider_category_keeps_its_first_row():
    """RC1 listed first as non-default and then as default is **not** a default, because the index
    upstream reads keeps the first row. Collecting every row marked default reported a product the
    jar accepts."""
    tables = {
        "rider_categories.txt": [
            {"_row_number": 2, "rider_category_id": "RC1", "is_default_fare_category": 0},
            {"_row_number": 3, "rider_category_id": "RC1", "is_default_fare_category": 1},
            {"_row_number": 4, "rider_category_id": "RC2", "is_default_fare_category": 1},
        ],
        "fare_products.txt": [
            {"_row_number": 2, "fare_product_id": "FP1", "rider_category_id": "RC1"},
            {"_row_number": 3, "fare_product_id": "FP1", "rider_category_id": "RC2"},
        ],
    }
    assert fire_file("fare_product_with_multiple_default_rider_categories", tables) == []


def test_an_out_of_enum_value_reports_UNRECOGNIZED():
    """The generated enum's own name for a folded value, not the empty string.

    Every caller was spelling `enum_name(...) or ""`, which produced "" for exactly the values this
    is most likely to be asked about, so seven call sites shared one defect and the fallback moved
    into the helper. Measured on a route_type of 99 in an in-seat transfer.
    """
    from gtfs_validator.rules._shared.enums import enum_name

    assert enum_name("routes.txt", "route_type", 3) == "BUS"
    assert enum_name("routes.txt", "route_type", -1) == "UNRECOGNIZED"
    assert enum_name("stops.txt", "location_type", -1) == "UNRECOGNIZED"


def test_the_locale_helper_matches_fifty_oracled_tags():
    """Four oracle runs, each adding shapes the previous had not covered, each finding a defect.

    The counts tell the story: 17 tags found nothing, then 14 more found two rules, then 12 more
    found the extlang limit, then 8 more found three. A corpus assembled from what comes to mind
    tests what the implementation already does.
    """
    from gtfs_validator.rules._shared.locales import canonical, language_tag

    # Only the first extlang survives; BCP 47 allows three.
    assert language_tag("zh-cmn-yue") == "cmn"
    assert language_tag("zh-min-nan-Hant") == "min-Hant"
    # A private-use-only tag keeps its subtag order, and und before it disappears.
    assert language_tag("x-b-a") == "x-b-a"
    assert canonical("x-b-a") == canonical("und-x-b-a")
    assert canonical("x-b-a") != canonical("x-a-b")
    # Unicode attributes de-duplicate; a repeated singleton keeps its first section.
    assert language_tag("en-u-abc-abc") == "en-u-abc"
    assert language_tag("en-a-foo-a-bar") == "en-a-foo"


def test_stop_access_only_means_something_for_a_platform_in_a_station():
    """Measured on `access_times`. The two branches are opposites, so exactly one can apply to a row,
    and both report stopAccess and locationType as enum names."""
    rows = [
        {
            "_row_number": 2,
            "stop_id": "ST1",
            "stop_name": "Station",
            "location_type": 1,
            "parent_station": None,
            "stop_access": None,
        },
        {
            "_row_number": 3,
            "stop_id": "P1",
            "stop_name": "Plat One",
            "location_type": 0,
            "parent_station": "ST1",
            "stop_access": 1,
        },
        {
            "_row_number": 4,
            "stop_id": "P2",
            "stop_name": "Plat Two",
            "location_type": 0,
            "parent_station": None,
            "stop_access": 1,
        },
        {
            "_row_number": 5,
            "stop_id": "ST2",
            "stop_name": "Station Two",
            "location_type": 1,
            "parent_station": None,
            "stop_access": 0,
        },
        {
            "_row_number": 6,
            "stop_id": "E1",
            "stop_name": "Entrance",
            "location_type": 2,
            "parent_station": "ST1",
            "stop_access": 1,
        },
    ]
    no_parent = [
        n.context
        for row in rows
        for n in fire("stop_access_specified_for_stop_with_no_parent_station", row)
    ]
    assert no_parent == [
        {
            "csvRowNumber": 4,
            "stopId": "P2",
            "stopName": "Plat Two",
            "stopAccess": "NOT_ACCESSIBLE_VIA_PATHWAYS",
            "locationType": "STOP",
        }
    ]
    wrong_place = [
        n.context for row in rows for n in fire("stop_access_specified_for_incorrect_location", row)
    ]
    assert [(c["csvRowNumber"], c["locationType"], c["stopAccess"]) for c in wrong_place] == [
        (5, "STATION", "ACCESSIBLE_VIA_PATHWAYS"),
        (6, "ENTRANCE", "NOT_ACCESSIBLE_VIA_PATHWAYS"),
    ]


def test_the_previous_departure_baseline_skips_rows_without_one():
    """Measured on `access_times`: row 3 has an arrival and no departure, row 4 departs at 08:20, and
    row 5 arrives at 08:10, which is compared against 08:20 rather than against row 3.

    `specifiedField` names the field that is present, which reads backwards and is why both branches
    are asserted here.
    """
    tables = {
        "stop_times.txt": [
            {
                "_row_number": 2,
                "trip_id": "TA",
                "stop_sequence": 1,
                "arrival_time": 28800,
                "departure_time": 28800,
            },
            {
                "_row_number": 3,
                "trip_id": "TA",
                "stop_sequence": 2,
                "arrival_time": 29100,
                "departure_time": None,
            },
            {
                "_row_number": 4,
                "trip_id": "TA",
                "stop_sequence": 3,
                "arrival_time": None,
                "departure_time": 30000,
            },
            {
                "_row_number": 5,
                "trip_id": "TA",
                "stop_sequence": 4,
                "arrival_time": 29400,
                "departure_time": 29520,
            },
        ]
    }
    assert [
        n.context
        for n in fire_file("stop_time_with_arrival_before_previous_departure_time", tables)
    ] == [
        {
            "csvRowNumber": 5,
            "prevCsvRowNumber": 4,
            "tripId": "TA",
            "arrivalTime": "08:10:00",
            "departureTime": "08:20:00",
        }
    ]
    got = [n.context for n in fire_file("stop_time_with_only_arrival_or_departure_time", tables)]
    assert [(c["csvRowNumber"], c["specifiedField"]) for c in got] == [
        (3, "arrival_time"),
        (4, "departure_time"),
    ]


def test_agency_id_on_routes_and_fare_attributes_follows_the_agency_count():
    """The same absent field is a recommendation or an error depending on another table's size.

    RouteAgencyIdValidator and FareAttributeAgencyIdValidator are the third and fourth emitters of
    missing_recommended_field, and this codebase had the first two. A probe built for
    stop_without_zone_id happened to include fare_attributes.txt, a table no earlier probe
    carried, and the jar reported a notice we did not.

    Measured both ways: with two agencies the jar reports missing_required_agency_id carrying only
    filename and csvRowNumber, because the validator passes null for the agency name.
    """
    from gtfs_validator.rules import registry

    registry.load_rules()
    one_agency = {
        "agency.txt": [{"_row_number": 2, "agency_id": "A1", "agency_name": "First"}],
        "routes.txt": [{"_row_number": 3, "route_id": "R2", "agency_id": None}],
        "fare_attributes.txt": [{"_row_number": 2, "fare_id": "F2", "agency_id": None}],
    }
    recommended = [
        n.context
        for n in registry.FILE_REGISTRY["missing_recommended_field"].func(
            FakeFeed(one_agency), CTX
        )
    ]
    assert {(row["filename"], row["fieldName"]) for row in recommended} >= {
        ("routes.txt", "agency_id"),
        ("fare_attributes.txt", "agency_id"),
    }

    two_agencies = dict(one_agency)
    two_agencies["agency.txt"] = [
        {"_row_number": 2, "agency_id": "A1", "agency_name": "First"},
        {"_row_number": 3, "agency_id": "A2", "agency_name": "Second"},
    ]
    required = [
        n.context
        for n in registry.FILE_REGISTRY["missing_required_agency_id"].func(
            FakeFeed(two_agencies), CTX
        )
    ]
    assert {"filename": "routes.txt", "csvRowNumber": 3} in required
    assert {"filename": "fare_attributes.txt", "csvRowNumber": 2} in required
    # And the recommendation is gone, because the condition moved.
    assert [
        row
        for row in (
            n.context
            for n in registry.FILE_REGISTRY["missing_recommended_field"].func(
                FakeFeed(two_agencies), CTX
            )
        )
        if row["fieldName"] == "agency_id" and row["filename"] != "agency.txt"
    ] == []


def test_no_agencies_at_all_reports_neither_agency_id_notice():
    """Zero agencies is a third case, not the "one agency" branch of a two-way condition.

    Measured on a feed whose agency.txt is a bare header and whose routes.txt and
    fare_attributes.txt each leave agency_id blank: the jar reports nothing, where reading
    `0 > 1` as "recommend it" reported two notices. Found by a probe from a review's own set
    rather than by anything in this suite.
    """
    from gtfs_validator.rules import registry

    registry.load_rules()
    tables = {
        "agency.txt": [],
        "routes.txt": [{"_row_number": 2, "route_id": "R1", "agency_id": None}],
        "fare_attributes.txt": [{"_row_number": 2, "fare_id": "F1", "agency_id": None}],
    }
    for code in ("missing_recommended_field", "missing_required_agency_id"):
        reported = [
            n.context for n in registry.FILE_REGISTRY[code].func(FakeFeed(tables), CTX)
        ]
        assert [row for row in reported if row.get("filename") != "agency.txt"] == []


def test_the_conditional_tables_come_out_in_the_jars_order():
    """fare_attributes before routes, measured. A comment once claimed the opposite."""
    from gtfs_validator.rules import registry

    registry.load_rules()
    tables = {
        "agency.txt": [{"_row_number": 2, "agency_id": "A1", "agency_name": "First"}],
        "routes.txt": [{"_row_number": 2, "route_id": "R1", "agency_id": None}],
        "fare_attributes.txt": [{"_row_number": 2, "fare_id": "F1", "agency_id": None}],
    }
    reported = [
        n.context
        for n in registry.FILE_REGISTRY["missing_recommended_field"].func(FakeFeed(tables), CTX)
    ]
    assert [row["filename"] for row in reported if row["fieldName"] == "agency_id"] == [
        "fare_attributes.txt",
        "routes.txt",
    ]
