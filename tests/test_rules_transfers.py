"""The transfer, block, shape-distance and in-seat rules, and the windows around them.

Split out of `test_rules_usage.py`, which had grown past the file-size limit while holding
two unrelated groups of rules. Fixtures are shared through `usagefeed`; the expectations
here were each measured on their own probe feed, named in the test that asserts them.
"""

from __future__ import annotations

from fakefeed import FakeFeed
from gtfs_validator.rules import registry
from usagefeed import CTX, fire, stop_row


def test_a_transfer_may_only_name_a_platform_or_a_station():
    """Measured on `tsfeed`. Both ends of every transfer are checked, so row 5 draws two
    notices, and the notice carries five fields: the manifest lists four, omitting
    locationTypeName."""
    tables = {
        "stops.txt": [
            stop_row(2, "S1", 0),
            stop_row(3, "ST1", 1),
            stop_row(4, "E1", 2, "ST1"),
            stop_row(5, "G1", 3, "ST1"),
            stop_row(6, "B1", 4, "S1"),
        ],
        "transfers.txt": [
            {"_row_number": 2, "from_stop_id": "S1", "to_stop_id": "ST1", "transfer_type": 0},
            {"_row_number": 3, "from_stop_id": "E1", "to_stop_id": "S1", "transfer_type": 0},
            {"_row_number": 4, "from_stop_id": "S1", "to_stop_id": "G1", "transfer_type": 0},
            {"_row_number": 5, "from_stop_id": "B1", "to_stop_id": "E1", "transfer_type": 0},
        ],
    }
    got = fire("transfer_with_invalid_stop_location_type", tables)
    assert got == [
        {
            "csvRowNumber": 3,
            "stopIdFieldName": "from_stop_id",
            "stopId": "E1",
            "locationTypeValue": 2,
            "locationTypeName": "ENTRANCE",
        },
        {
            "csvRowNumber": 4,
            "stopIdFieldName": "to_stop_id",
            "stopId": "G1",
            "locationTypeValue": 3,
            "locationTypeName": "GENERIC_NODE",
        },
        {
            "csvRowNumber": 5,
            "stopIdFieldName": "from_stop_id",
            "stopId": "B1",
            "locationTypeValue": 4,
            "locationTypeName": "BOARDING_AREA",
        },
        {
            "csvRowNumber": 5,
            "stopIdFieldName": "to_stop_id",
            "stopId": "E1",
            "locationTypeValue": 2,
            "locationTypeName": "ENTRANCE",
        },
    ]
    # An end naming a stop that does not exist is skipped, not reported.
    missing_end = dict(tables)
    missing_end["transfers.txt"] = [
        {"_row_number": 2, "from_stop_id": "NOPE", "to_stop_id": "ALSO", "transfer_type": 0}
    ]
    assert fire("transfer_with_invalid_stop_location_type", missing_end) == []


def booking_stop_time(
    number, pickup=None, drop_off=None, start=None, end=None, pickup_rule=None, drop_off_rule=None
):
    return {
        "_row_number": number,
        "trip_id": "T1",
        "stop_sequence": number,
        "location_group_id": "LG1",
        "pickup_type": pickup,
        "drop_off_type": drop_off,
        "start_pickup_drop_off_window": start,
        "end_pickup_drop_off_window": end,
        "pickup_booking_rule_id": pickup_rule,
        "drop_off_booking_rule_id": drop_off_rule,
    }


def test_a_phone_booked_window_needs_its_booking_rule():
    """Measured on `tsfeed`. Row 5 sets both types to MUST_PHONE with both windows, and draws
    **two** notices with identical context: the duplicate is the contract, since upstream's two
    branches are independent. Row 6 omits drop_off_type entirely, and the key is dropped rather
    than rendered, because upstream passes null for the type its branch is not about."""
    tables = {
        "booking_rules.txt": [{"_row_number": 2, "booking_rule_id": "BR1", "booking_type": 0}],
        "stop_times.txt": [
            booking_stop_time(2, pickup=0, drop_off=0),
            booking_stop_time(3, pickup=2, drop_off=0, start=32400, end=36000),
            booking_stop_time(4, pickup=0, drop_off=2, start=32400, end=36000),
            booking_stop_time(5, pickup=2, drop_off=2, start=32400, end=36000),
            booking_stop_time(6, pickup=2, start=32400, end=36000),
            booking_stop_time(
                7,
                pickup=2,
                drop_off=0,
                start=32400,
                end=36000,
                pickup_rule="BR1",
                drop_off_rule="BR1",
            ),
        ],
    }
    assert fire("missing_pickup_drop_off_booking_rule_id", tables) == [
        {"csvRowNumber": 3, "pickupType": "MUST_PHONE", "dropOffType": "REGULAR"},
        {"csvRowNumber": 4, "pickupType": "REGULAR", "dropOffType": "MUST_PHONE"},
        {"csvRowNumber": 5, "pickupType": "MUST_PHONE", "dropOffType": "MUST_PHONE"},
        {"csvRowNumber": 5, "pickupType": "MUST_PHONE", "dropOffType": "MUST_PHONE"},
        {"csvRowNumber": 6, "pickupType": "MUST_PHONE"},
    ]
    # Gated on booking_rules.txt existing at all.
    without_rules = {"stop_times.txt": tables["stop_times.txt"]}
    assert fire("missing_pickup_drop_off_booking_rule_id", without_rules) == []


def test_a_block_serving_two_route_types_is_reported():
    """Measured on `misc3`. Both list fields are ", "-joined strings rather than arrays, and the
    types are enum names: "R_BUS, R_RAIL" and "BUS, RAIL"."""
    tables = {
        "routes.txt": [
            {"_row_number": 2, "route_id": "R_BUS", "route_type": 3},
            {"_row_number": 3, "route_id": "R_RAIL", "route_type": 2},
        ],
        "trips.txt": [
            {"_row_number": 2, "route_id": "R_BUS", "trip_id": "T1", "block_id": "BLK1"},
            {"_row_number": 3, "route_id": "R_RAIL", "trip_id": "T2", "block_id": "BLK1"},
            {"_row_number": 4, "route_id": "R_BUS", "trip_id": "T3", "block_id": "BLK2"},
        ],
    }
    assert fire("inconsistent_route_type_for_block_id", tables) == [
        {"blockId": "BLK1", "routeIds": "R_BUS, R_RAIL", "routeTypes": "BUS, RAIL"}
    ]
    # A blank block_id is not a block, and a block of one type is consistent.
    blank = dict(tables)
    blank["trips.txt"] = [
        {"_row_number": 2, "route_id": "R_BUS", "trip_id": "T1", "block_id": None},
        {"_row_number": 3, "route_id": "R_RAIL", "trip_id": "T2", "block_id": None},
    ]
    assert fire("inconsistent_route_type_for_block_id", blank) == []


def test_a_route_that_does_not_exist_contributes_no_type():
    """Upstream filters the lookup to present routes, so a block of one real route and one broken
    reference is consistent here: the broken reference is foreign_key_violation's to report."""
    tables = {
        "routes.txt": [{"_row_number": 2, "route_id": "R_BUS", "route_type": 3}],
        "trips.txt": [
            {"_row_number": 2, "route_id": "R_BUS", "trip_id": "T1", "block_id": "BLK1"},
            {"_row_number": 3, "route_id": "NOPE", "trip_id": "T2", "block_id": "BLK1"},
        ],
    }
    got = fire("inconsistent_route_type_for_block_id", tables)
    assert got == []


def test_distances_on_the_stop_times_need_distances_on_the_shape():
    """Measured on `misc3`. The check is asymmetric: one stop time carrying shape_dist_traveled is
    enough to expect it, and every shape point must carry it to satisfy the expectation."""
    tables = {
        "trips.txt": [{"_row_number": 2, "trip_id": "T1", "shape_id": "SH1"}],
        "stop_times.txt": [
            {"_row_number": 2, "trip_id": "T1", "stop_sequence": 1, "shape_dist_traveled": 0},
            {"_row_number": 3, "trip_id": "T1", "stop_sequence": 2, "shape_dist_traveled": 100},
        ],
        "shapes.txt": [
            {"_row_number": 2, "shape_id": "SH1", "shape_pt_sequence": 1, "shape_dist_traveled": 0},
            {
                "_row_number": 3,
                "shape_id": "SH1",
                "shape_pt_sequence": 2,
                "shape_dist_traveled": None,
            },
        ],
    }
    assert fire("trip_with_shape_dist_traveled_but_no_shape_distances", tables) == [
        {"tripCsvRowNumber": 2, "tripId": "T1", "shapeId": "SH1", "stopTimeCsvRowNumber": 2}
    ]
    # Every point carrying a distance satisfies it.
    complete = dict(tables)
    complete["shapes.txt"] = [
        dict(tables["shapes.txt"][0]),
        dict(tables["shapes.txt"][1], shape_dist_traveled=100),
    ]
    assert fire("trip_with_shape_dist_traveled_but_no_shape_distances", complete) == []
    # No stop time carrying a distance means nothing is expected.
    without = dict(tables)
    without["stop_times.txt"] = [
        dict(row, shape_dist_traveled=None) for row in tables["stop_times.txt"]
    ]
    assert fire("trip_with_shape_dist_traveled_but_no_shape_distances", without) == []
    # A trip naming no shape, and a shape nobody defined, are both someone else's notice.
    no_shape = dict(tables)
    no_shape["trips.txt"] = [{"_row_number": 2, "trip_id": "T1", "shape_id": None}]
    assert fire("trip_with_shape_dist_traveled_but_no_shape_distances", no_shape) == []
    unknown = dict(tables)
    unknown["shapes.txt"] = []
    assert fire("trip_with_shape_dist_traveled_but_no_shape_distances", unknown) == []


def test_an_in_seat_transfer_between_two_modes_is_reported():
    """Measured on `cont_seat`: the route types report as enum names, and type 5, in-seat *not*
    allowed, carries no expectation because it says the transfer is impossible."""
    tables = {
        "routes.txt": [
            {"_row_number": 2, "route_id": "R_BUS", "route_type": 3},
            {"_row_number": 3, "route_id": "R_RAIL", "route_type": 2},
        ],
        "transfers.txt": [
            {
                "_row_number": 2,
                "from_route_id": "R_BUS",
                "to_route_id": "R_RAIL",
                "transfer_type": 4,
            },
            {
                "_row_number": 3,
                "from_route_id": "R_BUS",
                "to_route_id": "R_BUS",
                "transfer_type": 4,
            },
            {
                "_row_number": 4,
                "from_route_id": "R_BUS",
                "to_route_id": "R_RAIL",
                "transfer_type": 0,
            },
            {"_row_number": 5, "from_route_id": "R_BUS", "to_route_id": "NOPE", "transfer_type": 4},
        ],
    }
    assert fire("inconsistent_route_type_for_in_seat_transfer", tables) == [
        {
            "csvRowNumber": 2,
            "fromRouteId": "R_BUS",
            "toRouteId": "R_RAIL",
            "fromRouteType": "BUS",
            "toRouteType": "RAIL",
        }
    ]


def test_a_continuous_route_may_not_have_pickup_windows():
    """Measured on `cont_seat`. Only three of the four continuous values count, so a route declaring
    not-allowed or nothing at all is never reported, and one window is enough to fire: the absent one
    renders as 00:00:00, the GtfsTime default."""
    tables = {
        "routes.txt": [
            {"_row_number": 2, "route_id": "R_CONT", "route_type": 3, "continuous_pickup": 0},
            {
                "_row_number": 3,
                "route_id": "R_PLAIN",
                "route_type": 3,
                "continuous_pickup": 1,
                "continuous_drop_off": 1,
            },
        ],
        "trips.txt": [
            {"_row_number": 2, "route_id": "R_CONT", "trip_id": "T_CONT"},
            {"_row_number": 3, "route_id": "R_PLAIN", "trip_id": "T_PLAIN"},
        ],
        "stop_times.txt": [
            {
                "_row_number": 2,
                "trip_id": "T_CONT",
                "stop_sequence": 1,
                "start_pickup_drop_off_window": 32400,
                "end_pickup_drop_off_window": 36000,
            },
            {"_row_number": 3, "trip_id": "T_CONT", "stop_sequence": 2},
            {
                "_row_number": 4,
                "trip_id": "T_PLAIN",
                "stop_sequence": 1,
                "start_pickup_drop_off_window": 32400,
                "end_pickup_drop_off_window": 36000,
            },
        ],
    }
    assert fire("forbidden_continuous_pickup_drop_off", tables) == [
        {
            "routeCsvRowNumber": 2,
            "tripId": "T_CONT",
            "stopTimeCsvRowNumber": 2,
            "startPickupDropOffWindow": "09:00:00",
            "endPickupDropOffWindow": "10:00:00",
        }
    ]
    # One window is enough, and the other renders as the GtfsTime default.
    one_sided = dict(tables)
    one_sided["stop_times.txt"] = [
        {
            "_row_number": 2,
            "trip_id": "T_CONT",
            "stop_sequence": 1,
            "start_pickup_drop_off_window": 32400,
        }
    ]
    assert fire("forbidden_continuous_pickup_drop_off", one_sided) == [
        {
            "routeCsvRowNumber": 2,
            "tripId": "T_CONT",
            "stopTimeCsvRowNumber": 2,
            "startPickupDropOffWindow": "09:00:00",
            "endPickupDropOffWindow": "00:00:00",
        }
    ]


def test_the_continuous_rule_iterates_entities_not_indexes():
    """Upstream walks routes in file order, then that route's trips, then windowed stop times.

    Nothing is de-duplicated, because it iterates entities: a duplicated continuous route is reported
    once per row and two trips sharing an id are two trips. Measured on a probe with both, where a
    pair of dicts halved the count.
    """
    tables = {
        "routes.txt": [
            {"_row_number": 2, "route_id": "RC", "route_type": 3, "continuous_pickup": 0},
            {"_row_number": 3, "route_id": "RC", "route_type": 3, "continuous_pickup": 0},
        ],
        "trips.txt": [
            {"_row_number": 2, "route_id": "RC", "trip_id": "TD"},
            {"_row_number": 3, "route_id": "RC", "trip_id": "TD"},
        ],
        "stop_times.txt": [
            {
                "_row_number": 2,
                "trip_id": "TD",
                "stop_sequence": 1,
                "start_pickup_drop_off_window": 32400,
                "end_pickup_drop_off_window": 36000,
            },
        ],
    }
    got = fire("forbidden_continuous_pickup_drop_off", tables)
    # Two route rows times two trip rows, each naming the one windowed stop time.
    assert len(got) == 4
    assert [row["routeCsvRowNumber"] for row in got] == [2, 2, 3, 3]


def test_a_duplicate_route_id_keeps_its_first_type():
    """RD defined first as a bus and then as rail is a bus, as the single-key index has it, so a
    transfer from RD to a rail route is a mismatch. Overwriting reported nothing."""
    tables = {
        "routes.txt": [
            {"_row_number": 2, "route_id": "RD", "route_type": 3},
            {"_row_number": 3, "route_id": "RD", "route_type": 2},
            {"_row_number": 4, "route_id": "RR", "route_type": 2},
        ],
        "transfers.txt": [
            {"_row_number": 2, "from_route_id": "RD", "to_route_id": "RR", "transfer_type": 4}
        ],
    }
    got = fire("inconsistent_route_type_for_in_seat_transfer", tables)
    assert [(row["fromRouteType"], row["toRouteType"]) for row in got] == [("BUS", "RAIL")]


IN_SEAT_TABLES = {
    "stops.txt": [
        stop_row(2, "ST1", 1),
        stop_row(3, "P1", 0, "ST1"),
        stop_row(4, "P2", 0, "ST1"),
        stop_row(5, "P3", 0, "ST1"),
    ],
    "stop_times.txt": [
        {"_row_number": 2, "trip_id": "TA", "stop_id": "P1", "stop_sequence": 1},
        {"_row_number": 3, "trip_id": "TA", "stop_id": "P2", "stop_sequence": 2},
        {"_row_number": 4, "trip_id": "TA", "stop_id": "P3", "stop_sequence": 3},
        {"_row_number": 5, "trip_id": "TB", "stop_id": "P1", "stop_sequence": 1},
        {"_row_number": 6, "trip_id": "TB", "stop_id": "P2", "stop_sequence": 2},
        {"_row_number": 7, "trip_id": "TB", "stop_id": "P3", "stop_sequence": 3},
    ],
}


def in_seat_transfer(number, from_stop, to_stop, transfer_type=4):
    return {
        "_row_number": number,
        "from_stop_id": from_stop,
        "to_stop_id": to_stop,
        "from_trip_id": "TA",
        "to_trip_id": "TB",
        "transfer_type": transfer_type,
    }


def test_an_in_seat_transfer_may_not_end_at_a_station():
    """Two validators emit this code and they disagree about stations: an ordinary transfer between
    two stations draws nothing, and an in-seat one draws two notices, one per direction. Measured on
    `inseat`, where having only the first half reported nothing."""
    tables = dict(IN_SEAT_TABLES)
    tables["transfers.txt"] = [in_seat_transfer(2, "ST1", "ST1")]
    got = fire("transfer_with_invalid_stop_location_type", tables)
    assert [
        (row["csvRowNumber"], row["stopIdFieldName"], row["locationTypeName"]) for row in got
    ] == [
        (2, "from_stop_id", "STATION"),
        (2, "to_stop_id", "STATION"),
    ]
    # The same pair as an ordinary transfer draws nothing: stations are valid endpoints there.
    ordinary = dict(tables)
    ordinary["transfers.txt"] = [in_seat_transfer(2, "ST1", "ST1", transfer_type=0)]
    assert fire("transfer_with_invalid_stop_location_type", ordinary) == []


def test_an_in_seat_transfer_must_happen_where_one_trip_ends_and_the_next_begins():
    """The `from` stop must be the last of its trip and the `to` stop the first of its trip, because
    the vehicle continues. Measured on `inseat`: P2 mid-trip draws two notices and P3-to-P1 draws
    none."""
    tables = dict(IN_SEAT_TABLES)
    tables["transfers.txt"] = [in_seat_transfer(2, "P2", "P2")]
    got = fire("transfer_with_suspicious_mid_trip_in_seat", tables)
    assert got == [
        {
            "csvRowNumber": 2,
            "stopIdFieldName": "from_stop_id",
            "stopId": "P2",
            "tripIdFieldName": "from_trip_id",
            "tripId": "TA",
        },
        {
            "csvRowNumber": 2,
            "stopIdFieldName": "to_stop_id",
            "stopId": "P2",
            "tripIdFieldName": "to_trip_id",
            "tripId": "TB",
        },
    ]
    correct = dict(tables)
    correct["transfers.txt"] = [in_seat_transfer(2, "P3", "P1")]
    assert fire("transfer_with_suspicious_mid_trip_in_seat", correct) == []
    # A stop the trip never visits is a broken reference, not this notice.
    absent = dict(tables)
    absent["transfers.txt"] = [in_seat_transfer(2, "NOPE", "ALSO")]
    assert fire("transfer_with_suspicious_mid_trip_in_seat", absent) == []
    # Type 5 is validated identically: it names a specific pair of trips at a specific stop.
    not_allowed = dict(tables)
    not_allowed["transfers.txt"] = [in_seat_transfer(2, "P2", "P2", transfer_type=5)]
    assert len(fire("transfer_with_suspicious_mid_trip_in_seat", not_allowed)) == 2


def test_the_in_seat_half_is_emitted_before_the_endpoint_half():
    """Upstream registers TransfersInSeatTransferTypeValidator ahead of TransfersStopTypeValidator,
    and above the 1,000-sample cap that order decides which notices a report keeps. Measured on a
    1,800-notice mixed feed, where the jar's thousand samples are all stations."""
    tables = dict(IN_SEAT_TABLES)
    tables["stops.txt"] = [*IN_SEAT_TABLES["stops.txt"], stop_row(6, "ENT", 2, "ST1")]
    tables["transfers.txt"] = [
        {"_row_number": 2, "from_stop_id": "ENT", "to_stop_id": "P1", "transfer_type": 0},
        in_seat_transfer(3, "ST1", "P3"),
    ]
    got = fire("transfer_with_invalid_stop_location_type", tables)
    # The in-seat station comes first even though its transfer is on the later row.
    assert [row["locationTypeName"] for row in got] == ["STATION", "ENTRANCE"]


def test_only_the_in_seat_half_depends_on_stop_times():
    """With a failed stop_times.txt the jar still reports an entrance endpoint and stops reporting
    the in-seat station, so the two halves cannot share one gate."""
    tables = dict(IN_SEAT_TABLES)
    tables["stops.txt"] = [*IN_SEAT_TABLES["stops.txt"], stop_row(6, "ENT", 2, "ST1")]
    tables["transfers.txt"] = [
        {"_row_number": 2, "from_stop_id": "ENT", "to_stop_id": "P1", "transfer_type": 0},
        in_seat_transfer(3, "ST1", "P3"),
    ]
    registry.load_rules()
    feed = FakeFeed(tables, unindexable=frozenset({"stop_times.txt"}))
    got = [
        n.context
        for n in registry.FILE_REGISTRY["transfer_with_invalid_stop_location_type"].func(feed, CTX)
    ]
    assert [row["locationTypeName"] for row in got] == ["ENTRANCE"]


def test_the_suspicious_rule_needs_the_stop_to_exist_in_stops():
    """Upstream resolves the stop in stops.txt first, so a stop that appears only in stop_times.txt
    draws nothing, and a failed stops.txt silences the rule."""
    tables = dict(IN_SEAT_TABLES)
    tables["stops.txt"] = [stop_row(2, "P1", 0), stop_row(3, "P3", 0)]
    tables["transfers.txt"] = [in_seat_transfer(2, "P2", "P2")]
    assert fire("transfer_with_suspicious_mid_trip_in_seat", tables) == []
    registry.load_rules()
    feed = FakeFeed(
        dict(IN_SEAT_TABLES, **{"transfers.txt": [in_seat_transfer(2, "P2", "P2")]}),
        unindexable=frozenset({"stops.txt"}),
    )
    assert (
        list(registry.FILE_REGISTRY["transfer_with_suspicious_mid_trip_in_seat"].func(feed, CTX))
        == []
    )
