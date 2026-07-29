"""The two stops.txt entity rules, asserted against measured jar output.

The probe was a stops.txt carrying one row per location type with the name
blank, plus a row leaving location_type blank, plus a row whose description
repeats its name in different case.
"""

import datetime

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import run_rules
from gtfs_validator.schema import load_schemas
from gtfs_validator.store import FeedStore
from gtfs_validator.table_status import TableLoad


def _loads(columns_by_file):
    return {name: TableLoad(columns=columns) for name, columns in columns_by_file.items()}


CTX = Context(date=datetime.date(2026, 7, 24), country_code="US")

# GtfsLocationType: 0 stop, 1 station, 2 entrance, 3 generic node, 4 boarding area.
STOP, STATION, ENTRANCE, GENERIC_NODE, BOARDING_AREA = 0, 1, 2, 3, 4


def fire(code, row):
    registry.load_rules()
    return list(registry.REGISTRY[code].func(row, CTX))


def stop(**fields):
    row = {
        "stop_id": "S1",
        "stop_name": None,
        "stop_desc": None,
        "location_type": None,
        "_row_number": 2,
    }
    row.update(fields)
    return row


def test_a_stop_without_a_name_is_reported_with_its_type_name():
    # The notice carries the enum's constant name, not its number. The generated
    # manifest lists only csvRowNumber and stopId for this code, so it is
    # incomplete here; the jar prints locationType and that is what parity means.
    notices = fire("missing_stop_name", stop(stop_id="S2", location_type=STOP, _row_number=3))
    assert [n.context for n in notices] == [
        {"csvRowNumber": 3, "locationType": "STOP", "stopId": "S2"}
    ]


def test_a_station_and_an_entrance_without_a_name_are_reported():
    for location_type, name in ((STATION, "STATION"), (ENTRANCE, "ENTRANCE")):
        notices = fire("missing_stop_name", stop(location_type=location_type))
        assert notices[0].context["locationType"] == name


def test_a_generic_node_or_boarding_area_without_a_name_is_not_reported():
    # Only location types 0, 1 and 2 require a name.
    for location_type in (GENERIC_NODE, BOARDING_AREA):
        assert fire("missing_stop_name", stop(location_type=location_type)) == [], location_type


def test_an_absent_location_type_defaults_to_stop():
    notices = fire("missing_stop_name", stop(stop_id="S7", location_type=None, _row_number=8))
    assert [n.context for n in notices] == [
        {"csvRowNumber": 8, "locationType": "STOP", "stopId": "S7"}
    ]


def test_a_named_stop_is_not_reported():
    assert fire("missing_stop_name", stop(stop_name="Main St", location_type=STOP)) == []


def test_a_description_repeating_the_name_is_reported():
    notices = fire(
        "same_name_and_description_for_stop",
        stop(stop_id="S8", stop_name="Elm St", stop_desc="elm st", _row_number=9),
    )
    assert [n.context for n in notices] == [
        {"csvRowNumber": 9, "stopId": "S8", "stopDesc": "elm st"}
    ]


def test_a_real_description_is_not_reported():
    assert (
        fire(
            "same_name_and_description_for_stop",
            stop(stop_name="Oak St", stop_desc="Real description"),
        )
        == []
    )


def test_a_stop_with_no_description_is_not_reported():
    assert fire("same_name_and_description_for_stop", stop(stop_name="Main St")) == []


def test_neither_rule_runs_without_stop_name_or_location_type_columns(tmp_path):
    # shouldCallValidate skips the whole validator, so a stops.txt carrying only
    # an id and coordinates produces nothing even though its row would otherwise
    # be a nameless stop. Measured: the jar reports nothing for exactly that feed.
    store = FeedStore.open(tmp_path / "feed.db")
    schema = load_schemas()["stops.txt"]
    store.create_table(schema)
    store.insert_rows(schema, [{"stop_id": "S1", "_row_number": 2}])

    bare = NoticeContainer()
    run_rules(store, bare, CTX, loads=_loads({"stops.txt": frozenset({"stop_id"})}))
    # Scoped to the two stop-name codes rather than asserting an empty container:
    # file rules also run here, and a store with no calendar.txt legitimately
    # draws missing_calendar_and_calendar_date_files.
    assert Notice("missing_stop_name", Severity.ERROR).mapping_key not in bare.grouped()
    assert (
        Notice("same_name_and_description_for_stop", Severity.WARNING).mapping_key
        not in bare.grouped()
    )

    named = NoticeContainer()
    run_rules(store, named, CTX, loads=_loads({"stops.txt": frozenset({"stop_id", "stop_name"})}))
    assert Notice("missing_stop_name", Severity.ERROR).mapping_key in named.grouped()


def located(stop_id, location_type, row_number, lat=None, lon=None):
    return {
        "stop_id": stop_id,
        "location_type": location_type,
        "stop_lat": lat,
        "stop_lon": lon,
        "_row_number": row_number,
    }


def test_a_stop_station_or_entrance_without_coordinates_is_reported():
    # Measured: those three types are reported and their names carried, while a
    # generic node and a boarding area are not.
    for location_type, name in ((STOP, "STOP"), (STATION, "STATION"), (ENTRANCE, "ENTRANCE")):
        notices = fire("stop_without_location", located("A", location_type, 2))
        assert [n.context for n in notices] == [
            {"csvRowNumber": 2, "locationType": name, "stopId": "A"}
        ], location_type
    for location_type in (GENERIC_NODE, BOARDING_AREA):
        assert fire("stop_without_location", located("A", location_type, 2)) == [], location_type


def test_only_one_coordinate_is_not_enough():
    # hasStopLatLon needs both. Measured on a stop carrying only a latitude.
    for lat, lon in ((40.7, None), (None, -74.0)):
        assert len(fire("stop_without_location", located("F", STOP, 7, lat, lon))) == 1, (lat, lon)


def test_both_coordinates_present_is_fine():
    assert fire("stop_without_location", located("A", STOP, 2, 40.7, -74.0)) == []
