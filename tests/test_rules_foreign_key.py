"""foreign_key_violation over the generated references, and the gating that decides most cases.

Every expectation was measured by running the jar on the named probe. The hand-written six live in
`test_rules_foreign_key_handwritten`; the split is by responsibility, this half being the shape the
annotation processor generates.
"""

from __future__ import annotations

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CODE = "foreign_key_violation"
CTX = Context(date=datetime.date(2026, 6, 15), country_code="US")

ROUTES = [{"_row_number": 2, "route_id": "R1", "route_type": 3}]
TRIP = {"_row_number": 2, "route_id": "R1", "service_id": "WEEK", "trip_id": "T1"}
CALENDAR = [{"_row_number": 2, "service_id": "WEEK"}]


def fire(tables, unindexable=frozenset()):
    registry.load_rules()
    view = FakeFeed(tables, unindexable=unindexable)
    return [notice.context for notice in registry.FILE_REGISTRY[CODE].func(view, CTX)]


def test_a_valid_feed_is_silent():
    """Measured on `fkv1`."""
    assert fire({"routes.txt": ROUTES, "trips.txt": [TRIP], "calendar.txt": CALENDAR}) == []


def test_a_dangling_route_id_reports_all_six_context_keys():
    """Measured on `fkv2`."""
    trip = {**TRIP, "route_id": "GHOST"}
    assert fire({"routes.txt": ROUTES, "trips.txt": [trip], "calendar.txt": CALENDAR}) == [
        {
            "childFilename": "trips.txt",
            "childFieldName": "route_id",
            "parentFilename": "routes.txt",
            "parentFieldName": "route_id",
            "fieldValue": "GHOST",
            "csvRowNumber": 2,
        }
    ]


def test_an_absent_child_value_is_skipped():
    """Measured on `fkv3`: a shape_id column present and empty draws nothing.

    The key set to None is how the double says "declared but blank": `FakeFeed.has_column` is
    "any row carries the key", so the presence of the key is the header and its value is the cell.
    """
    trip = {**TRIP, "shape_id": None}
    assert fire({"routes.txt": ROUTES, "trips.txt": [trip], "calendar.txt": CALENDAR}) == []


def test_an_absent_parent_file_still_reports():
    """Measured on `fkv4`: no shapes.txt at all, and the jar reports SH1."""
    trip = {**TRIP, "shape_id": "SH1"}
    reported = fire({"routes.txt": ROUTES, "trips.txt": [trip], "calendar.txt": CALENDAR})
    assert [(row["childFieldName"], row["fieldValue"]) for row in reported] == [("shape_id", "SH1")]


def test_a_header_only_parent_table_reports():
    """Measured on `fkv21`: shapes.txt present with no rows behaves as an empty parent."""
    trip = {**TRIP, "shape_id": "SH1"}
    tables = {
        "routes.txt": ROUTES,
        "trips.txt": [trip],
        "calendar.txt": CALENDAR,
        "shapes.txt": [],
    }
    assert [row["fieldValue"] for row in fire(tables)] == ["SH1"]


def test_a_duplicated_parent_key_resolves():
    """Measured on `fkv22`: two routes sharing one route_id, and the jar reports no violation."""
    routes = [
        {"_row_number": 2, "route_id": "RDUP", "route_type": 3},
        {"_row_number": 3, "route_id": "RDUP", "route_type": 3},
    ]
    trip = {**TRIP, "route_id": "RDUP"}
    assert fire({"routes.txt": routes, "trips.txt": [trip], "calendar.txt": CALENDAR}) == []


def test_a_column_the_file_never_declared_is_not_queried_at_all():
    """`shouldCallValidate` is `hasColumn`, and what it buys is a scan not run.

    Asserting silence here would be a test that cannot fail, and it was one until a review pointed
    it out: a column absent from the header holds NULL in every row, so the anti-join skips it and
    the notice count is zero with or without the gate. Verified by forcing `has_column` to return
    true, which left the old assertion passing.

    What the gate actually changes is cost. Without it, a feed declaring none of stop_times' optional
    reference columns still scans stop_times once per absent column, which on a large feed is the
    difference between about ten scans and fifty. So the observable this pins is the query, not the
    output.
    """
    asked = []

    class Spy(FakeFeed):
        def rows_missing_reference(self, child, column, parents, *, skip_empty=False):
            asked.append((child, column))
            return super().rows_missing_reference(child, column, parents, skip_empty=skip_empty)

    registry.load_rules()
    # trips.txt declares route_id and service_id but not shape_id.
    view = Spy({"routes.txt": ROUTES, "trips.txt": [TRIP], "calendar.txt": CALENDAR})
    list(registry.FILE_REGISTRY[CODE].func(view, CTX))
    assert ("trips.txt", "route_id") in asked
    assert ("trips.txt", "shape_id") not in asked


def test_an_unparsable_child_table_silences_every_reference_from_it():
    """Measured on `fkv16`: an empty required service_id beside a dangling route_id draws neither.

    The decisive probe for gating. A merely-dropped row would still leave route_id reported, so
    silence here is what says upstream skipped the whole validator: trips.txt is UNPARSABLE_ROWS
    and `dependenciesHaveErrors` holds.
    """
    trip = {**TRIP, "route_id": "GHOST"}
    tables = {"routes.txt": ROUTES, "trips.txt": [trip], "calendar.txt": CALENDAR}
    assert fire(tables, unindexable=frozenset({"trips.txt"})) == []


def test_an_unparsable_parent_table_silences_only_its_own_references():
    """Measured on `fkv25`: a routes.txt row missing route_type, and trips.route_id goes unchecked.

    The other half of the gate, and the reason the rule cannot let DependencyFailed escape: the
    dangling stop_id in the same feed is still reported, because stops.txt parsed.
    """
    trip = {**TRIP, "route_id": "GHOST"}
    stop_time = {"_row_number": 2, "trip_id": "T1", "stop_id": "GHOSTSTOP", "stop_sequence": 1}
    tables = {
        "routes.txt": ROUTES,
        "trips.txt": [trip],
        "calendar.txt": CALENDAR,
        "stops.txt": [{"_row_number": 2, "stop_id": "S1"}],
        "stop_times.txt": [stop_time],
    }
    reported = fire(tables, unindexable=frozenset({"routes.txt"}))
    assert [(row["childFilename"], row["fieldValue"]) for row in reported] == [
        ("stop_times.txt", "GHOSTSTOP")
    ]


def test_the_samples_come_out_in_upstream_validator_order():
    """Measured on `fkv11`: four tables violating at once.

    frequencies, stop_times, transfers, then trips' two, which is ascending validator class name.
    """
    tables = {
        "routes.txt": ROUTES,
        "calendar.txt": CALENDAR,
        "stops.txt": [{"_row_number": 2, "stop_id": "S2"}],
        "trips.txt": [{**TRIP, "route_id": "GHOSTROUTE", "shape_id": "GHOSTSHAPE"}],
        "stop_times.txt": [
            {"_row_number": 2, "trip_id": "T1", "stop_id": "GHOSTSTOP", "stop_sequence": 1}
        ],
        "frequencies.txt": [{"_row_number": 2, "trip_id": "GHOSTTRIP"}],
        "transfers.txt": [{"_row_number": 2, "from_stop_id": "GHOSTFROM", "to_stop_id": "S2"}],
    }
    reported = fire(tables)
    assert [(row["childFilename"], row["childFieldName"]) for row in reported] == [
        ("frequencies.txt", "trip_id"),
        ("stop_times.txt", "stop_id"),
        ("transfers.txt", "from_stop_id"),
        ("trips.txt", "route_id"),
        ("trips.txt", "shape_id"),
    ]
