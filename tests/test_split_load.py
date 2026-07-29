"""The giant-table load split: tagged ops, the merge, and the split worker."""

from gtfs_validator.notices import Notice, Severity
from gtfs_validator.split_load import TaggedRecordingContainer, merge_ops

CAPS = (1000, 1000)


def notice(code, row):
    return Notice(code, Severity.WARNING, {"csvRowNumber": row})


def test_typing_ops_tag_their_row_and_merge_in_row_order():
    left = TaggedRecordingContainer(CAPS, record_parse=True)
    right = TaggedRecordingContainer(CAPS, record_parse=False)
    left.typing_row(2)
    left.add(notice("a", 2))
    right.typing_row(3)
    right.add(notice("a", 3))
    left.typing_row(4)
    left.add(notice("a", 4))
    ops = merge_ops([left.tagged, right.tagged])
    assert [op[1].context["csvRowNumber"] for op in ops] == [2, 3, 4]
    assert all(op[0] == "add" for op in ops)


def test_parse_ops_settle_before_their_next_record():
    # Sequentially, a parse notice for a malformed line is emitted between the
    # previous yield and the next one, so it must sort immediately before the
    # next record's typing ops whichever worker owns that record.
    zero = TaggedRecordingContainer(CAPS, record_parse=True)
    other = TaggedRecordingContainer(CAPS, record_parse=False)
    zero.typing_row(2)
    zero.add(notice("typed", 2))
    mark = zero.parse_mark()
    zero.parse_mode = True
    zero.add(notice("invalid_row_length", 3))
    zero.parse_mode = False
    zero.settle_parse_tags(mark, 4)  # the next yielded record is row 4, owned elsewhere
    other.typing_row(4)
    other.add(notice("typed", 4))
    ops = merge_ops([zero.tagged, other.tagged])
    assert [op[1].code for op in ops] == ["typed", "invalid_row_length", "typed"]


def test_non_zero_workers_record_no_parse_ops():
    worker = TaggedRecordingContainer(CAPS, record_parse=False)
    worker.parse_mode = True
    worker.add(notice("invalid_row_length", 3))
    worker.parse_mode = False
    assert worker.tagged == []


def test_trailing_parse_ops_settle_after_every_record():
    zero = TaggedRecordingContainer(CAPS, record_parse=True)
    zero.typing_row(9)
    zero.add(notice("typed", 9))
    mark = zero.parse_mark()
    zero.parse_mode = True
    zero.add(notice("too_many_rows", 10))
    zero.parse_mode = False
    zero.settle_parse_tags(mark, None)  # the stream ended without another record
    ops = merge_ops([zero.tagged])
    assert [op[1].code for op in ops] == ["typed", "too_many_rows"]


def test_header_merge_ops_sort_before_the_first_record():
    from gtfs_validator.notices import NoticeContainer

    zero = TaggedRecordingContainer(CAPS, record_parse=True)
    mark = zero.parse_mark()
    zero.parse_mode = True
    header = NoticeContainer()
    header.add(notice("unknown_column", 1))
    zero.merge(header)
    zero.parse_mode = False
    zero.settle_parse_tags(mark, 2)
    zero.typing_row(2)
    zero.add(notice("typed", 2))
    ops = merge_ops([zero.tagged])
    assert ops[0][0] == "merge"
    assert ops[1][0] == "add"


def test_split_workers_reproduce_the_sequential_load(tmp_path):
    # Three workers, a stop_times.txt whose rows carry a typing error and a
    # short row: the merged ops replayed must equal the sequential loader's
    # notices exactly, and the union of the scratch stores must hold exactly
    # the rows the sequential store holds.
    import zipfile

    from gtfs_validator.loading import _load_table
    from gtfs_validator.notices import NoticeContainer
    from gtfs_validator.schema import load_schemas
    from gtfs_validator.split_load import split_worker
    from gtfs_validator.store import FeedStore

    feed_path = tmp_path / "feed.zip"
    with zipfile.ZipFile(feed_path, "w") as archive:
        archive.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence,unknown_col\n"
            "T1,08:00:00,08:00:00,S1,1,x\n"
            "T1,bad-time,08:10:00,S2,2,x\n"
            "T1,08:20:00\n"
            "T1,08:30:00,08:30:00,S3,3,x\n"
            "T1,08:40:00,08:40:00,S4,4,x\n",
        )

    from gtfs_validator.container import open_feed

    schema = load_schemas()["stop_times.txt"]
    sequential = NoticeContainer()
    feed = open_feed(feed_path)
    with FeedStore.open(tmp_path / "seq.db") as seq_store:
        _load_table(feed, schema, seq_store, sequential, "")
        seq_rows = [tuple(row) for row in seq_store.rows("stop_times.txt")]
    feed.close()

    workers = 3
    streams, stored = [], []
    for index in range(workers):
        load, tagged, failure = split_worker(
            str(feed_path),
            "stop_times.txt",
            workers,
            index,
            str(tmp_path / f"w{index}.db"),
            "",
            (
                sequential.max_total,
                sequential.max_per_type,
            ),
        )
        assert failure is None
        assert load.columns == schema_columns_of(schema)
        streams.append(tagged)
        # A fresh FeedStore has an empty schema registry and answers rows() with
        # nothing, so the scratch stores are read raw, exactly as the ATTACH copy
        # will read them.
        import sqlite3

        with sqlite3.connect(tmp_path / f"w{index}.db") as connection:
            stored.extend(connection.execute('SELECT * FROM "stop_times.txt"'))

    from gtfs_validator.parallel_load import _replay
    from gtfs_validator.split_load import merge_ops

    replayed = NoticeContainer()
    _replay(replayed, merge_ops(streams))
    assert [(n.code, n.context) for n in replayed.in_order()] == [
        (n.code, n.context) for n in sequential.in_order()
    ]
    assert replayed._counts == sequential._counts
    assert replayed.error_count() == sequential.error_count()
    assert sorted(stored) == sorted(seq_rows)


def schema_columns_of(schema):
    return frozenset(
        ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence", "unknown_col"]
    )


def test_the_split_path_stays_byte_identical_through_the_cli(tmp_path, monkeypatch):
    # The threshold drops to one byte so the messy feed's every table takes the
    # split path in the main process (workers never read the constant), and the
    # whole CLI must still produce byte-identical reports at every -t.
    import json
    import sys

    sys.path.insert(0, "tests")
    from gtfs_validator import parallel_load
    from gtfs_validator.cli import main
    from test_parallel_load import _messy_feed

    monkeypatch.setattr(parallel_load, "_SPLIT_BYTES", 1)
    feed = tmp_path / "feed.zip"
    _messy_feed(feed)

    def run(threads):
        out = tmp_path / f"t{threads}"
        assert main(["-i", str(feed), "-o", str(out), "-d", "2026-07-27", "-t", str(threads)]) == 0
        from test_parallel_load import _reports

        return _reports(out)

    one = run(1)
    three = run(3)
    assert one == three
    assert len(json.loads(one[0])["notices"]) > 3
