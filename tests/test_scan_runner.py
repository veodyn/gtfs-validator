"""The runner's scan-hub stage: one stored pass, same notices, same order."""

import datetime

from gtfs_validator.context import Context
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.rules.runner import run_rules
from gtfs_validator.schema import load_schemas
from gtfs_validator.store import FeedStore
from gtfs_validator.table_status import TableLoad

CTX = Context(date=datetime.date(2026, 6, 1), country_code="")

STOP_TIME_COLUMNS = frozenset(
    {"trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time", "timepoint"}
)


def _store_with_stop_times(tmp_path, rows):
    store = FeedStore.open(tmp_path / "feed.db")
    schema = load_schemas()["stop_times.txt"]
    store.create_table(schema)
    store.insert_rows(schema, rows)
    return store


def test_scan_rules_report_through_the_hub(tmp_path):
    # One row trips both timepoint branches: exact timepoint with no times draws
    # two stop_time_timepoint_without_times, and a timed row without a timepoint
    # draws missing_timepoint_value. The codes are hub-registered, so this passes
    # only if the hub feeds their consumers and the runner merges their buffers.
    store = _store_with_stop_times(
        tmp_path,
        [
            {"trip_id": "T1", "stop_sequence": 1, "timepoint": 1, "_row_number": 2},
            {
                "trip_id": "T1",
                "stop_sequence": 2,
                "arrival_time": 28800,
                "departure_time": 28800,
                "_row_number": 3,
            },
        ],
    )
    notices = NoticeContainer()
    run_rules(
        store,
        notices,
        CTX,
        loads={"stop_times.txt": TableLoad(columns=STOP_TIME_COLUMNS)},
        system_errors=NoticeContainer(),
    )
    grouped = notices.grouped()
    exact = grouped["stop_time_timepoint_without_times2"]
    assert [n.context["specifiedField"] for n in exact] == ["arrival_time", "departure_time"]
    assert [n.context["csvRowNumber"] for n in grouped["missing_timepoint_value1"]] == [3]


def test_the_hub_reads_the_table_once_for_its_rules(tmp_path):
    # The point of the hub: its scan rules together cost one pass. The entity
    # pass and the cached shared helpers keep their own single passes, so this
    # counts reads made by the hub stage alone, against the real registry.
    from gtfs_validator.rules.registry import SCAN_REGISTRY, load_rules
    from gtfs_validator.rules.runner import FeedView, _run_scan_hubs

    load_rules()
    store = _store_with_stop_times(
        tmp_path,
        [{"trip_id": "T1", "stop_sequence": 1, "timepoint": 1, "_row_number": 2}],
    )
    reads = []
    original = store.rows

    def counting_rows(filename):
        reads.append(filename)
        return original(filename)

    store.rows = counting_rows
    view = FeedView(
        store, {"stop_times.txt": TableLoad(columns=STOP_TIME_COLUMNS)}, frozenset(loads_present)
    )
    results = _run_scan_hubs(view, CTX, NoticeContainer())
    # The two timepoint rules apply on this header; both must have come from the
    # single read, and no scan rule may have opened a pass of its own.
    assert reads.count("stop_times.txt") == 1
    assert "stop_time_timepoint_without_times" in results
    assert "missing_timepoint_value" in results
    assert set(results) <= set(SCAN_REGISTRY)


loads_present = {"stop_times.txt"}
