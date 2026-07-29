import pytest

from gtfs_validator.error_ids import AppError, ErrorIds
from gtfs_validator.schema import Field, FieldType, Presence, TableSchema
from gtfs_validator.store import FeedStore, quote_identifier

STOPS = TableSchema(
    "stops.txt",
    Presence.REQUIRED,
    ("stop_id",),
    (
        Field("stop_id", FieldType.ID, Presence.REQUIRED),
        Field("stop_name", FieldType.TEXT, Presence.OPTIONAL),
        Field("stop_lat", FieldType.LATITUDE, Presence.OPTIONAL),
    ),
)
CALENDAR = TableSchema(
    "calendar.txt",
    Presence.OPTIONAL,
    ("service_id",),
    (
        Field("service_id", FieldType.ID, Presence.REQUIRED),
        Field("start_date", FieldType.DATE, Presence.REQUIRED),
    ),
)


@pytest.fixture
def store():
    with FeedStore.open() as feed_store:
        feed_store.create_table(STOPS)
        yield feed_store


def test_rows_round_trip_with_their_row_numbers(store):
    store.insert_rows(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "S1", "stop_name": "Main", "stop_lat": 40.7},
            {"_row_number": 3, "stop_id": "S2", "stop_name": None, "stop_lat": None},
        ],
    )
    rows = list(store.rows("stops.txt"))
    assert [r["stop_id"] for r in rows] == ["S1", "S2"]
    assert [r["_row_number"] for r in rows] == [2, 3]
    assert rows[1]["stop_name"] is None
    assert rows[0]["stop_lat"] == 40.7


def test_required_fields_are_still_nullable(store):
    # A row missing a required field is stored anyway: every rule must see it,
    # and upstream stores it too. NOT NULL here would hide the reported rows.
    store.insert_rows(STOPS, [{"_row_number": 2, "stop_id": None, "stop_name": "X"}])
    assert store.count("stops.txt") == 1


def test_dates_are_stored_sortably():
    with FeedStore.open() as store:
        store.create_table(CALENDAR)
        store.insert_rows(
            CALENDAR,
            [
                {"_row_number": 2, "service_id": "A", "start_date": (2026, 1, 30)},
                {"_row_number": 3, "service_id": "B", "start_date": (2025, 12, 31)},
            ],
        )
        ordered = store.query("SELECT service_id FROM 'calendar.txt' ORDER BY start_date")
        assert [r["service_id"] for r in ordered] == ["B", "A"]


def test_insert_streams_rather_than_materialising(store):
    consumed = []

    def generate():
        for i in range(5000):
            consumed.append(i)
            yield {
                "_row_number": i + 2,
                "stop_id": f"S{i}",
                "stop_name": None,
                "stop_lat": None,
            }

    store.insert_rows(STOPS, generate())
    assert store.count("stops.txt") == 5000
    assert len(consumed) == 5000


def test_query_exposes_sql_for_joins(store):
    store.insert_rows(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "S1", "stop_name": "A", "stop_lat": 1.0},
            {"_row_number": 3, "stop_id": "S1", "stop_name": "B", "stop_lat": 2.0},
        ],
    )
    duplicates = store.query(
        "SELECT stop_id, COUNT(*) AS n FROM 'stops.txt' GROUP BY stop_id HAVING n > 1"
    )
    assert [(r["stop_id"], r["n"]) for r in duplicates] == [("S1", 2)]


def test_missing_table_reports_zero_and_yields_nothing(store):
    assert store.count("routes.txt") == 0
    assert list(store.rows("routes.txt")) == []
    assert not store.has_table("routes.txt")


def test_identifier_guard_accepts_real_table_and_column_names():
    assert quote_identifier("stop_times.txt") == '"stop_times.txt"'
    assert quote_identifier("_row_number") == '"_row_number"'


@pytest.mark.parametrize("name", ['stops" ; DROP TABLE x --', "", "1abc", "a b", "a'b"])
def test_identifier_guard_refuses_anything_else(name):
    # SQLite cannot bind an identifier, so the store interpolates them. Nothing
    # outside the generated registry should ever reach that path; this makes the
    # property checked rather than merely asserted in a comment.
    with pytest.raises(AppError) as raised:
        quote_identifier(name)
    assert raised.value.id is ErrorIds.STORE_UNSAFE_IDENTIFIER


def _three_stops_two_names(store):
    """Rows whose stop_name repeats out of order, so a grouped read has to do some work.

    Row 2 is "Main", row 3 "Side", row 4 "Main" again, and row 5 has no name at all. The
    repeat is deliberately not adjacent: a grouped read that simply chunked consecutive rows
    would pass on adjacent duplicates and fail here.
    """
    store.insert_rows(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "S1", "stop_name": "Main"},
            {"_row_number": 3, "stop_id": "S2", "stop_name": "Side"},
            {"_row_number": 4, "stop_id": "S3", "stop_name": "Main"},
            {"_row_number": 5, "stop_id": "S4", "stop_name": None},
        ],
    )


def test_distinct_in_file_order_takes_first_appearance_and_drops_nulls(store):
    """The order a map keyed on the column would have been populated in.

    "Main" comes first because row 2 does, even though its group also holds row 4. A NULL is
    not a key: a row missing a required column never reached upstream's container.
    """
    _three_stops_two_names(store)
    assert list(store.distinct_in_file_order("stops.txt", "stop_name")) == ["Main", "Side"]


def test_rows_where_returns_one_keys_rows_in_file_order(store):
    _three_stops_two_names(store)
    store.create_index("stops.txt", "stop_name")
    rows = list(store.rows_where("stops.txt", "stop_name", "Main"))
    assert [row["_row_number"] for row in rows] == [2, 4]
    assert list(store.rows_where("stops.txt", "stop_name", "Nowhere")) == []


def test_rows_where_works_without_the_index_too(store):
    """The index is a speed decision, not a correctness one, and nothing may depend on it."""
    _three_stops_two_names(store)
    assert [row["_row_number"] for row in store.rows_where("stops.txt", "stop_name", "Main")] == [
        2,
        4,
    ]


def test_create_index_is_idempotent(store):
    _three_stops_two_names(store)
    store.create_index("stops.txt", "stop_name")
    store.create_index("stops.txt", "stop_name")
    assert [row["_row_number"] for row in store.rows_where("stops.txt", "stop_name", "Side")] == [3]


def test_rows_for_keys_returns_each_asked_for_key(store):
    """One statement for several keys, each key's rows in file order.

    A key with no rows is absent rather than empty, which is what the caller batching over an
    ordered list has to handle, so it is pinned here rather than left to be discovered.
    """
    _three_stops_two_names(store)
    fetched = store.rows_for_keys("stops.txt", "stop_name", ["Side", "Main", "Nowhere"])
    assert sorted(fetched) == ["Main", "Side"]
    assert [row["_row_number"] for row in fetched["Main"]] == [2, 4]


def test_rows_for_keys_is_empty_for_an_empty_batch(store):
    """No keys means no statement: an empty `IN ()` is a syntax error in SQLite."""
    _three_stops_two_names(store)
    assert store.rows_for_keys("stops.txt", "stop_name", []) == {}


def test_rows_for_keys_agrees_with_rows_where_key_by_key(store):
    """The batched read and the single read are the same answer, which is the whole contract."""
    _three_stops_two_names(store)
    keys = ["Main", "Side"]
    batched = store.rows_for_keys("stops.txt", "stop_name", keys)
    for key in keys:
        one_at_a_time = [dict(row) for row in store.rows_where("stops.txt", "stop_name", key)]
        assert batched[key] == one_at_a_time


def test_rows_grouped_by_yields_whole_groups_with_non_adjacent_members(store):
    """Complete groups, in the column's order, with rows in file order inside each.

    The two "Main" rows are rows 2 and 4 with a "Side" row between them, so this pins that the
    scan gathers a whole group rather than a run of neighbours. The group order is the column's
    own and not first appearance, which is the whole reason a caller has to reorder.
    """
    _three_stops_two_names(store)
    grouped = list(store.rows_grouped_by("stops.txt", "stop_name"))
    assert [key for key, _ in grouped] == ["Main", "Side"]
    assert [[row["_row_number"] for row in rows] for _, rows in grouped] == [[2, 4], [3]]


def test_the_grouped_reads_are_empty_for_a_table_that_was_never_created(store):
    """A table the feed did not carry has no schema, and reading it is not an error."""
    assert list(store.distinct_in_file_order("calendar.txt", "service_id")) == []
    assert list(store.rows_where("calendar.txt", "service_id", "S1")) == []
    assert store.rows_for_keys("calendar.txt", "service_id", ["S1"]) == {}
    assert list(store.rows_grouped_by("calendar.txt", "service_id")) == []
    store.create_index("calendar.txt", "service_id")


def test_distinct_in_file_order_can_require_a_second_column(store):
    """`require` changes the key set, and therefore every later key's bucket.

    Row 3 is the only "Side" row and it has no latitude, so requiring one drops the key
    entirely rather than yielding it with nothing behind it.
    """
    store.insert_rows(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "S1", "stop_name": "Main", "stop_lat": 40.7},
            {"_row_number": 3, "stop_id": "S2", "stop_name": "Side", "stop_lat": None},
            {"_row_number": 4, "stop_id": "S3", "stop_name": "Rear", "stop_lat": 40.9},
        ],
    )
    assert list(store.distinct_in_file_order("stops.txt", "stop_name")) == ["Main", "Side", "Rear"]
    assert list(store.distinct_in_file_order("stops.txt", "stop_name", "stop_lat")) == [
        "Main",
        "Rear",
    ]


def test_on_disk_store_is_usable(tmp_path):
    path = tmp_path / "feed.sqlite"
    with FeedStore.open(path) as store:
        store.create_table(STOPS)
        store.insert_rows(STOPS, [{"_row_number": 2, "stop_id": "S1"}])
        assert store.count("stops.txt") == 1
    assert path.exists()


def test_rows_at_group_max_takes_last_file_order_row_of_the_greatest_key(store):
    """The argmax read: per group, the row with the greatest order value.

    The tie rule is the measured one from trip_shape_distance: among rows sharing
    the greatest order value, the last in file order wins, because the container
    sorts stably by the sequence and the validator takes get(size - 1). Rows with
    a null group or a null order value do not count at all.
    """
    store.insert_rows(
        STOPS,
        [
            # group A: plain case, greatest lat on row 4
            {"_row_number": 2, "stop_id": "A", "stop_name": "x", "stop_lat": 1.0},
            {"_row_number": 4, "stop_id": "A", "stop_name": "y", "stop_lat": 9.0},
            # group B: tie on lat, later row (6) must win
            {"_row_number": 5, "stop_id": "B", "stop_name": "first", "stop_lat": 3.0},
            {"_row_number": 6, "stop_id": "B", "stop_name": "second", "stop_lat": 3.0},
            # group C: only a null-order row, so no result at all
            {"_row_number": 7, "stop_id": "C", "stop_name": "z", "stop_lat": None},
            # null group: never counted
            {"_row_number": 8, "stop_id": None, "stop_name": "w", "stop_lat": 99.0},
        ],
    )
    result = {
        row["stop_id"]: row
        for row in store.rows_at_group_max("stops.txt", "stop_id", "stop_lat")
    }
    assert set(result) == {"A", "B"}
    assert result["A"]["stop_name"] == "y"
    assert result["B"]["stop_name"] == "second"
    assert result["B"]["_row_number"] == 6


def test_group_counts_counts_non_null_groups(store):
    store.insert_rows(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "A", "stop_name": None, "stop_lat": None},
            {"_row_number": 3, "stop_id": "A", "stop_name": None, "stop_lat": None},
            {"_row_number": 4, "stop_id": "B", "stop_name": None, "stop_lat": None},
            {"_row_number": 5, "stop_id": None, "stop_name": None, "stop_lat": None},
        ],
    )
    assert dict(store.group_counts("stops.txt", "stop_id")) == {"A": 2, "B": 1}


def test_rows_where_any_set_keeps_rows_with_any_named_column(store):
    """The window filter: a row counts when any of the named columns is non-null,
    and `require` must be non-null besides. File order."""
    store.insert_rows(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "A", "stop_name": "x", "stop_lat": None},
            {"_row_number": 3, "stop_id": "B", "stop_name": None, "stop_lat": 1.0},
            {"_row_number": 4, "stop_id": "C", "stop_name": None, "stop_lat": None},
            {"_row_number": 5, "stop_id": None, "stop_name": "y", "stop_lat": None},
        ],
    )
    kept = list(
        store.rows_where_any_set(
            "stops.txt", ("stop_name", "stop_lat"), require="stop_id"
        )
    )
    assert [row["_row_number"] for row in kept] == [2, 3]


def test_rows_where_all_null_keeps_only_fully_absent_rows(store):
    store.insert_rows(
        STOPS,
        [
            {"_row_number": 2, "stop_id": "A", "stop_name": None, "stop_lat": None},
            {"_row_number": 3, "stop_id": None, "stop_name": "x", "stop_lat": None},
            {"_row_number": 4, "stop_id": None, "stop_name": None, "stop_lat": 5.0},
            {"_row_number": 5, "stop_id": None, "stop_name": None, "stop_lat": None},
        ],
    )
    kept = list(store.rows_where_all_null("stops.txt", ("stop_name", "stop_lat")))
    assert [row["_row_number"] for row in kept] == [2, 5]
