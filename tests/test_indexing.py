from gtfs_validator.indexing import check_indexes
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.schema import Field, FieldType, Presence, TableSchema
from gtfs_validator.store import FeedStore

STOPS = TableSchema(
    "stops.txt",
    Presence.REQUIRED,
    ("stop_id",),
    (Field("stop_id", FieldType.ID, Presence.REQUIRED),),
)
STOP_TIMES = TableSchema(
    "stop_times.txt",
    Presence.REQUIRED,
    ("trip_id", "stop_sequence"),
    (
        Field("trip_id", FieldType.ID, Presence.REQUIRED),
        Field("stop_sequence", FieldType.INTEGER, Presence.REQUIRED),
    ),
)
FEED_INFO = TableSchema(
    "feed_info.txt",
    Presence.OPTIONAL,
    (),
    (Field("feed_publisher_name", FieldType.TEXT, Presence.REQUIRED),),
    single_row=True,
)


def loaded(schema, rows):
    store = FeedStore.open()
    store.create_table(schema)
    store.insert_rows(schema, rows)
    return store


def found(notices, code):
    return [n for g in notices.grouped().values() for n in g if n.code == code]


def test_single_column_key_omits_the_second_field_pair():
    store = loaded(
        STOPS,
        [{"_row_number": 2, "stop_id": "S1"}, {"_row_number": 5, "stop_id": "S1"}],
    )
    notices = NoticeContainer()
    check_indexes(store, {"stops.txt": STOPS}, notices)
    store.close()
    # A single-column key sends no second pair at all rather than nulls.
    assert found(notices, "duplicate_key")[0].context == {
        "filename": "stops.txt",
        "oldCsvRowNumber": 2,
        "newCsvRowNumber": 5,
        "fieldName1": "stop_id",
        "fieldValue1": "S1",
    }


def test_composite_key_joins_defined_columns_into_field1():
    # Verified against the jar: a multi-column key sends one comma-joined
    # fieldName1/fieldValue1 and no fieldName2, not a field per column.
    store = loaded(
        STOP_TIMES,
        [
            {"_row_number": 2, "trip_id": "T1", "stop_sequence": 1},
            {"_row_number": 3, "trip_id": "T1", "stop_sequence": 1},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"stop_times.txt": STOP_TIMES}, notices)
    store.close()
    context = found(notices, "duplicate_key")[0].context
    assert context["fieldName1"] == "trip_id,stop_sequence"
    assert context["fieldValue1"] == "T1,1"
    assert "fieldName2" not in context


def test_three_rows_sharing_a_key_produce_two_notices():
    # Each row after the first is its own collision, paired with the first.
    store = loaded(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "S1"},
            {"_row_number": 5, "stop_id": "S1"},
            {"_row_number": 9, "stop_id": "S1"},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"stops.txt": STOPS}, notices)
    store.close()
    pairs = [
        (n.context["oldCsvRowNumber"], n.context["newCsvRowNumber"])
        for n in found(notices, "duplicate_key")
    ]
    assert pairs == [(2, 5), (2, 9)]


def test_nullable_composite_key_parts_still_collide():
    # fare_products keys on (fare_product_id, fare_media_id, rider_category_id)
    # with the last two optional. Two rows sharing the id and blank optionals
    # collide, and only the defined column is named. Verified against the jar.
    fare_products = TableSchema(
        "fare_products.txt",
        Presence.OPTIONAL,
        ("fare_product_id", "fare_media_id", "rider_category_id"),
        (
            Field("fare_product_id", FieldType.ID, Presence.REQUIRED),
            Field("fare_media_id", FieldType.ID, Presence.OPTIONAL),
            Field("rider_category_id", FieldType.ID, Presence.OPTIONAL),
        ),
    )
    store = loaded(
        fare_products,
        [
            {"_row_number": 2, "fare_product_id": "FP1"},
            {"_row_number": 3, "fare_product_id": "FP1"},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"fare_products.txt": fare_products}, notices)
    store.close()
    context = found(notices, "duplicate_key")[0].context
    assert context["fieldName1"] == "fare_product_id"
    assert context["fieldValue1"] == "FP1"
    assert "fieldName2" not in context


def test_distinct_keys_are_silent():
    store = loaded(
        STOPS,
        [{"_row_number": 2, "stop_id": "S1"}, {"_row_number": 3, "stop_id": "S2"}],
    )
    notices = NoticeContainer()
    check_indexes(store, {"stops.txt": STOPS}, notices)
    store.close()
    assert found(notices, "duplicate_key") == []


def test_a_null_key_is_not_a_duplicate():
    # Two rows each missing the key already drew missing_required_field in stage
    # 3. Reporting them as sharing a key would double-count one problem.
    store = loaded(
        STOPS,
        [{"_row_number": 2, "stop_id": None}, {"_row_number": 3, "stop_id": None}],
    )
    notices = NoticeContainer()
    check_indexes(store, {"stops.txt": STOPS}, notices)
    store.close()
    assert found(notices, "duplicate_key") == []


def test_more_than_one_entity_fires_for_single_row_tables():
    store = loaded(
        FEED_INFO,
        [
            {"_row_number": 2, "feed_publisher_name": "A"},
            {"_row_number": 3, "feed_publisher_name": "B"},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"feed_info.txt": FEED_INFO}, notices)
    store.close()
    assert found(notices, "more_than_one_entity")[0].context == {
        "filename": "feed_info.txt",
        "entityCount": 2,
    }


def test_one_row_in_a_single_row_table_is_silent():
    store = loaded(FEED_INFO, [{"_row_number": 2, "feed_publisher_name": "A"}])
    notices = NoticeContainer()
    check_indexes(store, {"feed_info.txt": FEED_INFO}, notices)
    store.close()
    assert found(notices, "more_than_one_entity") == []


def test_absent_tables_are_skipped():
    store = FeedStore.open()
    notices = NoticeContainer()
    check_indexes(store, {"stops.txt": STOPS}, notices)
    store.close()
    assert list(notices.grouped()) == []


def test_multiple_distinct_duplicate_groups_are_all_reported():
    # The single-pass window query must handle many separate duplicated keys, each
    # paired with its own first row, in one scan rather than a re-query per group.
    store = loaded(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "A"},
            {"_row_number": 3, "stop_id": "B"},
            {"_row_number": 4, "stop_id": "A"},
            {"_row_number": 5, "stop_id": "B"},
            {"_row_number": 6, "stop_id": "C"},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"stops.txt": STOPS}, notices)
    store.close()
    pairs = {
        (n.context["fieldValue1"], n.context["oldCsvRowNumber"], n.context["newCsvRowNumber"])
        for n in found(notices, "duplicate_key")
    }
    assert pairs == {("A", 2, 4), ("B", 3, 5)}


def test_dropped_table_is_not_indexed():
    # When a loader raises mid-file the partial table is dropped, so a duplicate
    # in the loaded prefix must not surface as a duplicate_key notice.
    store = loaded(
        STOPS,
        [{"_row_number": 2, "stop_id": "S1"}, {"_row_number": 3, "stop_id": "S1"}],
    )
    store.drop_table("stops.txt")
    assert not store.has_table("stops.txt")
    notices = NoticeContainer()
    check_indexes(store, {"stops.txt": STOPS}, notices)
    store.close()
    assert found(notices, "duplicate_key") == []


FREQUENCIES = TableSchema(
    "frequencies.txt",
    Presence.OPTIONAL,
    ("trip_id", "start_time"),
    (
        Field("trip_id", FieldType.ID, Presence.REQUIRED),
        Field("start_time", FieldType.TIME, Presence.REQUIRED),
    ),
)
CALENDAR_DATES = TableSchema(
    "calendar_dates.txt",
    Presence.OPTIONAL,
    ("service_id", "date"),
    (
        Field("service_id", FieldType.ID, Presence.REQUIRED),
        Field("date", FieldType.DATE, Presence.REQUIRED),
    ),
)


def test_key_values_are_rendered_by_field_type_not_by_storage():
    # The store holds a TIME as seconds since midnight, but upstream joins
    # GtfsTime.toString(). Measured against the jar: duplicate frequencies rows at
    # 08:00:00 report fieldValue1 "T1,08:00:00", not "T1,28800".
    store = loaded(
        FREQUENCIES,
        [
            {"_row_number": 2, "trip_id": "T1", "start_time": 8 * 3600},
            {"_row_number": 3, "trip_id": "T1", "start_time": 8 * 3600},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"frequencies.txt": FREQUENCIES}, notices)
    context = found(notices, "duplicate_key")[0].context
    assert context["fieldName1"] == "trip_id,start_time"
    assert context["fieldValue1"] == "T1,08:00:00"


def test_a_time_past_midnight_keeps_its_hour():
    # GtfsTime is a duration, not a clock reading, so 25:30:00 stays 25:30:00.
    store = loaded(
        FREQUENCIES,
        [
            {"_row_number": 2, "trip_id": "T1", "start_time": 25 * 3600 + 30 * 60},
            {"_row_number": 3, "trip_id": "T1", "start_time": 25 * 3600 + 30 * 60},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"frequencies.txt": FREQUENCIES}, notices)
    assert found(notices, "duplicate_key")[0].context["fieldValue1"] == "T1,25:30:00"


def test_a_date_key_renders_as_yyyymmdd():
    # GtfsDate.toString is toYYYYMMDD, which is what the store already holds.
    store = loaded(
        CALENDAR_DATES,
        [
            {"_row_number": 2, "service_id": "SV1", "date": 20260101},
            {"_row_number": 3, "service_id": "SV1", "date": 20260101},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"calendar_dates.txt": CALENDAR_DATES}, notices)
    assert found(notices, "duplicate_key")[0].context["fieldValue1"] == "SV1,20260101"


def test_interleaved_duplicate_groups_are_reported_in_source_row_order():
    # Upstream reports each offending row as it reaches it, so with groups A(2),
    # B(3), B(4), A(5) the row-4 duplicate comes first. Ordering by the group's
    # first row instead reverses them. Measured against the jar on a stops.txt of
    # exactly that shape. Order is not cosmetic: samples export in insertion
    # order and cap at 1,000, so past the cap a different order exports a
    # different set of samples.
    store = loaded(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "A"},
            {"_row_number": 3, "stop_id": "B"},
            {"_row_number": 4, "stop_id": "B"},
            {"_row_number": 5, "stop_id": "A"},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"stops.txt": STOPS}, notices)
    store.close()
    reported = [
        (n.context["oldCsvRowNumber"], n.context["newCsvRowNumber"])
        for n in found(notices, "duplicate_key")
    ]
    assert reported == [(3, 4), (2, 5)]


def test_a_composite_key_with_no_defined_component_sends_no_value():
    # transfers.txt's key components are all optional or conditional, so two rows
    # with every one blank collide on an empty key. Upstream's reduce over an
    # empty list yields null, and gson is not configured with serializeNulls, so
    # the jar's sample carries fieldName1 as "" and omits fieldValue1 entirely.
    schema = TableSchema(
        "transfers.txt",
        Presence.OPTIONAL,
        ("from_stop_id", "to_stop_id"),
        (
            Field("from_stop_id", FieldType.ID, Presence.OPTIONAL),
            Field("to_stop_id", FieldType.ID, Presence.OPTIONAL),
        ),
    )
    store = loaded(
        schema,
        [
            {"_row_number": 2, "from_stop_id": None, "to_stop_id": None},
            {"_row_number": 3, "from_stop_id": None, "to_stop_id": None},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"transfers.txt": schema}, notices)
    store.close()
    context = found(notices, "duplicate_key")[0].context
    assert context["fieldName1"] == ""
    assert context["fieldValue1"] is None


def test_a_composite_key_compares_type_defaults_not_nulls():
    """An unset int key column collides with an explicit 0, because Java's getter says 0.

    `CompositeKey.builder()` is fed the typed getters with no presence guard, so a blank
    transfer_count reads as 0 and duplicates a row that sets it to 0. Measured on `tcfeed`,
    where the jar reports a duplicate between rows 2 and 6 while grouping nulls separately
    reported none. That feed diverged for several plans with no entry in known-divergences,
    which is how a defect hides.

    The notice also describes the group's *first* row rather than the offending one: upstream
    passes `oldEntity` to `getDefinedKeys` and `getDefinedValues`. Row 2 sets transfer_count, so
    all three columns are named even though the offending row leaves it blank.
    """
    rules = TableSchema(
        "fare_transfer_rules.txt",
        Presence.OPTIONAL,
        ("from_leg_group_id", "to_leg_group_id", "transfer_count"),
        (
            Field("from_leg_group_id", FieldType.ID, Presence.OPTIONAL),
            Field("to_leg_group_id", FieldType.ID, Presence.OPTIONAL),
            Field("transfer_count", FieldType.INTEGER, Presence.OPTIONAL),
        ),
    )
    store = loaded(
        rules,
        [
            {"_row_number": 2, "from_leg_group_id": "L1", "to_leg_group_id": "L1",
             "transfer_count": 0},
            {"_row_number": 3, "from_leg_group_id": "L1", "to_leg_group_id": "L1",
             "transfer_count": None},
        ],
    )
    notices = NoticeContainer()
    check_indexes(store, {"fare_transfer_rules.txt": rules}, notices)
    store.close()
    context = found(notices, "duplicate_key")[0].context
    assert context["oldCsvRowNumber"] == 2
    assert context["newCsvRowNumber"] == 3
    assert context["fieldName1"] == "from_leg_group_id,to_leg_group_id,transfer_count"
    assert context["fieldValue1"] == "L1,L1,0"
