"""The five hand-written foreign key validators, whose parents the annotation cannot express.

Four resolve a key against either of two files; the fifth resolves against locations.geojson. Each
expectation names the probe it was measured on.
"""

from __future__ import annotations

from test_rules_foreign_key import CALENDAR, ROUTES, TRIP, fire


def test_a_service_id_in_neither_calendar_file_names_both():
    """Measured on `fkv14`: the label is plural `calendar_dates.txt`, unlike the Javadoc."""
    trip = {**TRIP, "service_id": "GHOSTSERVICE"}
    assert fire({"routes.txt": ROUTES, "trips.txt": [trip], "calendar.txt": CALENDAR}) == [
        {
            "childFilename": "trips.txt",
            "childFieldName": "service_id",
            "parentFilename": "calendar.txt or calendar_dates.txt",
            "parentFieldName": "service_id",
            "fieldValue": "GHOSTSERVICE",
            "csvRowNumber": 2,
        }
    ]


def test_a_service_id_found_only_in_calendar_dates_resolves():
    """Measured on `fkv6`: the union, not calendar.txt alone."""
    trip = {**TRIP, "service_id": "EXTRA"}
    tables = {
        "routes.txt": ROUTES,
        "trips.txt": [trip],
        "calendar.txt": CALENDAR,
        "calendar_dates.txt": [{"_row_number": 2, "service_id": "EXTRA", "date": "20260615"}],
    }
    assert fire(tables) == []


def test_the_handwritten_service_id_check_sorts_between_two_generated_ones():
    """Measured on `fkv15`: route_id, then service_id, then shape_id, from one trips.txt row.

    The probe that rules out "generated first, hand-written second": GtfsTripRouteId <
    GtfsTripServiceId < GtfsTripShapeId, so the hand-written validator interleaves.
    """
    trip = {
        **TRIP,
        "route_id": "GHOSTROUTE",
        "service_id": "GHOSTSERVICE",
        "shape_id": "GHOSTSHAPE",
    }
    tables = {"routes.txt": ROUTES, "trips.txt": [trip], "calendar.txt": CALENDAR}
    assert [row["childFieldName"] for row in fire(tables)] == ["route_id", "service_id", "shape_id"]


def test_a_network_id_resolves_against_routes_or_networks():
    """Measured on `fkv18`."""
    tables = {
        "routes.txt": ROUTES,
        "trips.txt": [TRIP],
        "calendar.txt": CALENDAR,
        "networks.txt": [{"_row_number": 2, "network_id": "N1"}],
        "fare_leg_rules.txt": [{"_row_number": 2, "network_id": "GHOSTNETWORK"}],
    }
    assert fire(tables) == [
        {
            "childFilename": "fare_leg_rules.txt",
            "childFieldName": "network_id",
            "parentFilename": "routes.txt or networks.txt",
            "parentFieldName": "network_id",
            "fieldValue": "GHOSTNETWORK",
            "csvRowNumber": 2,
        }
    ]


def test_both_join_rule_network_ids_report_from_one_row_in_code_order():
    """Measured on `fkv19`: from_network_id before to_network_id, one class, two checks."""
    join = {"_row_number": 2, "from_network_id": "GHOSTFROMNET", "to_network_id": "GHOSTTONET"}
    tables = {
        "routes.txt": ROUTES,
        "trips.txt": [TRIP],
        "calendar.txt": CALENDAR,
        "networks.txt": [{"_row_number": 2, "network_id": "N1"}],
        "fare_leg_join_rules.txt": [join],
    }
    reported = fire(tables)
    assert [row["childFieldName"] for row in reported] == ["from_network_id", "to_network_id"]


def test_a_location_id_resolves_against_the_geojson_feature_ids():
    """Measured on `fkv20`: the parent field prints as `id`, though the column is feature_id."""
    stop_time = {
        "_row_number": 3,
        "trip_id": "T1",
        "stop_sequence": 2,
        "location_id": "GHOSTLOCATION",
    }
    tables = {
        "routes.txt": ROUTES,
        "trips.txt": [TRIP],
        "calendar.txt": CALENDAR,
        "stop_times.txt": [stop_time],
        "locations.geojson": [{"_row_number": 1, "feature_id": "L1"}],
    }
    assert fire(tables) == [
        {
            "childFilename": "stop_times.txt",
            "childFieldName": "location_id",
            "parentFilename": "locations.geojson",
            "parentFieldName": "id",
            "fieldValue": "GHOSTLOCATION",
            "csvRowNumber": 3,
        }
    ]


def test_a_handwritten_check_can_sort_before_a_generated_one():
    """Measured on `fkv28`: fare_leg_join_rules before attributions, the reverse of file order.

    With `fkv29` this is the pair that rules out sorting by (child file, child field), which
    reproduces every other ordering observation.
    """
    join = {"_row_number": 2, "from_network_id": "GHOSTFROMNET", "to_network_id": "N1"}
    attribution = {"_row_number": 2, "attribution_id": "A1", "agency_id": "GHOSTAGENCY"}
    tables = {
        "routes.txt": ROUTES,
        "trips.txt": [TRIP],
        "calendar.txt": CALENDAR,
        "agency.txt": [{"_row_number": 2, "agency_id": "1"}],
        "networks.txt": [{"_row_number": 2, "network_id": "N1"}],
        "fare_leg_join_rules.txt": [join],
        "attributions.txt": [attribution],
    }
    reported = fire(tables)
    assert [row["childFilename"] for row in reported] == [
        "fare_leg_join_rules.txt",
        "attributions.txt",
    ]


def test_a_handwritten_check_can_sort_after_a_generated_one():
    """Measured on `fkv29`: trips.route_id before stop_times.location_id, reversing file order."""
    stop_time = {
        "_row_number": 3,
        "trip_id": "T1",
        "stop_sequence": 2,
        "location_id": "GHOSTLOCATION",
    }
    tables = {
        "routes.txt": ROUTES,
        "trips.txt": [{**TRIP, "route_id": "GHOSTROUTE"}],
        "calendar.txt": CALENDAR,
        "stop_times.txt": [stop_time],
        "locations.geojson": [{"_row_number": 1, "feature_id": "L1"}],
    }
    reported = fire(tables)
    assert [row["childFilename"] for row in reported] == ["trips.txt", "stop_times.txt"]
