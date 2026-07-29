from gtfs_validator.schema import (
    KNOWN_FILES,
    RECOMMENDED_FILES,
    REQUIRED_FILES,
    SINGLE_ROW_FILES,
    FieldReference,
    FieldType,
    Presence,
    load_schemas,
)


def test_registry_covers_every_csv_table():
    schemas = load_schemas()
    assert len(schemas) == 31
    assert "stop_times.txt" in schemas
    # The GeoJSON schema is not a CSV table and belongs to plan 5.
    assert "locations.geojson" not in schemas


def test_required_files_are_exactly_upstreams_required_tables():
    # Measured, not assumed. Upstream's engine emits missing_required_file only
    # for @Required tables. stops.txt is @ConditionallyRequired at table level;
    # its notice comes from MissingStopsFileValidator in the rule layer, and
    # feed_info.txt's comes from MissingFeedInfoValidator.
    assert frozenset({"agency.txt", "routes.txt", "stop_times.txt", "trips.txt"}) == REQUIRED_FILES
    assert frozenset() == RECOMMENDED_FILES


def test_fares_v2_tables_are_known():
    # Plan 1 hand-wrote a KNOWN_FILES list that omitted these entirely, so a
    # conformant Fares v2 feed drew one spurious unknown_file per table.
    for name in ("fare_media.txt", "fare_products.txt", "areas.txt", "networks.txt"):
        assert name in KNOWN_FILES, name


def test_single_row_tables_come_from_the_annotation():
    assert frozenset({"feed_info.txt"}) == SINGLE_ROW_FILES


def test_stop_times_declares_its_key_and_types():
    stop_times = load_schemas()["stop_times.txt"]
    assert stop_times.primary_key == ("trip_id", "stop_sequence")
    assert stop_times.field("trip_id").type is FieldType.ID
    assert stop_times.field("trip_id").references == FieldReference(
        table="trips.txt", field="trip_id", validator="GtfsStopTimeTripIdForeignKeyValidator"
    )
    assert stop_times.field("arrival_time").type is FieldType.TIME
    assert stop_times.field("arrival_time").presence is Presence.CONDITIONALLY_REQUIRED


def test_end_range_is_available_for_the_range_notices():
    arrival = load_schemas()["stop_times.txt"].field("arrival_time")
    assert arrival.end_range == ("departure_time", True)


def test_unknown_field_returns_none():
    assert load_schemas()["stops.txt"].field("no_such_column") is None


def test_enum_fields_carry_their_permitted_values():
    route_type = load_schemas()["routes.txt"].field("route_type")
    assert route_type.type is FieldType.ENUM
    assert 3 in route_type.enum_values


def test_column_names_are_available_for_unknown_column_checks():
    columns = load_schemas()["agency.txt"].column_names
    assert "agency_name" in columns
    assert "agency_timezone" in columns
