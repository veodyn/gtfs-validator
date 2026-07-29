"""Splitting one giant table's parse-and-type across workers.

Every split worker streams the identical full CSV member through `parse_table`,
which is the C-speed part, but types and stores only the records whose index
falls in its share. Notice ops are tagged with row numbers so the main process
can merge the workers' streams back into the exact sequential emission order
and hand them to the plan-11 replay unchanged.

Ownership rules, which are the whole correctness story:

- Record ``i`` (0-based count of yielded parsed records) belongs to worker
  ``i % workers``; only the owner types, stores, and records that record's ops.
- Parse-level notices are recorded by worker 0 alone, whose parse is the same
  full stream everyone runs. They are tagged with the row number of the *next*
  yielded record, because ``parse_table`` emits them between yields and that is
  exactly where they sit in the sequential stream; ops after the last record
  tag past ``MAX_ROW_NUMBER``.
- The retention simulation each container runs is safe on a subset stream: a
  worker's local per-type count only undercounts the merged stream, so an op it
  proves unretainable ("count") is unretainable globally, and a full "add" op
  re-applies the destination caps at replay.
"""

from __future__ import annotations

from pathlib import Path

from gtfs_validator.csvparse import MAX_ROW_NUMBER
from gtfs_validator.error_ids import carry
from gtfs_validator.loadops import _RecordingContainer
from gtfs_validator.schema import load_schemas
from gtfs_validator.store import FeedStore
from gtfs_validator.table_status import TableLoad

# The tag phases: parse ops sort before typing ops at the same row.
_PARSE = 0
_TYPING = 1
# Where end-of-stream parse ops sort: after every possible record.
_END = MAX_ROW_NUMBER + 2


class TaggedRecordingContainer(_RecordingContainer):
    """A recording container whose ops carry ``(row, phase, seq)`` sort tags.

    The base class's ops list stays the single source of truth for what was
    recorded; this class only decides each op's tag and whether it is recorded
    at all (`record_parse`). An aggregated counts op mutates in place in the
    base, and the tagged list holds the same reference, so later increments
    reach both without a new entry.
    """

    def __init__(self, caps: tuple[int, int], record_parse: bool) -> None:
        super().__init__(caps)
        self.tagged: list[tuple[tuple[int, int, int], tuple | list]] = []
        self.record_parse = record_parse
        self.parse_mode = False
        self._row = 0

    def typing_row(self, row_number: int) -> None:
        self._row = row_number

    def parse_mark(self) -> int:
        return len(self.tagged)

    def settle_parse_tags(self, mark: int, next_row: int | None) -> None:
        """Re-tag parse ops recorded since `mark` to their true position."""
        row = _END if next_row is None else next_row
        for index in range(mark, len(self.tagged)):
            (_, phase, seq), op = self.tagged[index]
            if phase is _PARSE:
                self.tagged[index] = ((row, _PARSE, seq), op)

    def add(self, notice) -> None:
        if self.parse_mode and not self.record_parse:
            return
        before = len(self.ops)
        super().add(notice)
        self._take(before)

    def merge(self, other) -> None:
        if self.parse_mode and not self.record_parse:
            return
        before = len(self.ops)
        super().merge(other)
        self._take(before)

    def _take(self, before: int) -> None:
        phase = _PARSE if self.parse_mode else _TYPING
        row = 0 if self.parse_mode else self._row
        for op in self.ops[before:]:
            self.tagged.append(((row, phase, len(self.tagged)), op))


def merge_ops(streams: list[list[tuple[tuple[int, int, int], tuple]]]) -> list[tuple]:
    """The workers' tagged streams as one plan-11 op list in sequential order.

    Tags cannot collide across workers: typing ops for a row exist only in its
    owner's stream and parse ops only in worker 0's, so the sort is total up to
    each stream's own stable `seq`.
    """
    combined = [entry for stream in streams for entry in stream]
    combined.sort(key=lambda entry: entry[0])
    return [op for _, op in combined]


def split_worker(
    archive: str,
    table: str,
    workers: int,
    index: int,
    db_path: str,
    country_code: str,
    caps: tuple[int, int],
):
    """One worker's share of a giant table: (load, tagged ops, carried exception).

    Runs in a spawned process. The pipeline is `loading._load_table`'s, with the
    share filter spliced between the parser and the typing stage: the full parse
    runs here exactly as it runs everywhere, and only records
    ``i % workers == index`` go on to be typed and stored.
    """
    from gtfs_validator.container import open_feed
    from gtfs_validator.csvparse import parse_table
    from gtfs_validator.loading import RECOMMENDED_COLUMNS, _required_columns, _typed_rows

    # One guard around everything, setup included: an open_feed or scratch-store
    # failure escaping through pool.starmap would abort the whole load instead
    # of letting _absorb_shares fall back to the sequential reload. Review
    # finding on plan 13.
    notices = None
    try:
        schema = load_schemas()[table]
        notices = TaggedRecordingContainer(caps, record_parse=index == 0)
        load = TableLoad()
        feed = open_feed(Path(archive))
        try:
            with FeedStore.open(Path(db_path)) as store:
                store.create_table(schema)
                parsed = parse_table(
                    feed,
                    schema.filename,
                    notices,
                    required_columns=_required_columns(schema),
                    recommended_columns=RECOMMENDED_COLUMNS.get(schema.filename, ()),
                    known_columns=schema.column_names,
                    load=load,
                    max_chars_per_column=schema.max_chars_per_column,
                )
                shared = _share_rows(parsed, notices, workers, index)
                store.insert_rows(schema, _typed_rows(schema, shared, notices, country_code, load))
        finally:
            feed.close()
    except Exception as exc:  # noqa: BLE001 - carried to the parent, reported there
        return None, notices.tagged if notices is not None else [], carry(exc)
    return load, notices.tagged, None


def _share_rows(parsed, notices, workers: int, index: int):
    """Yield only this worker's records, settling parse tags as the stream moves.

    `parsed` is `parse_table`'s generator. Ops recorded while the parser
    advances are parse-phase; they settle to the row number of the record that
    pull produced, or past the end when the stream finishes.
    """
    record_index = 0
    while True:
        mark = notices.parse_mark()
        notices.parse_mode = True
        try:
            row = next(parsed)
        except StopIteration:
            notices.parse_mode = False
            notices.settle_parse_tags(mark, None)
            return
        finally:
            notices.parse_mode = False
        notices.settle_parse_tags(mark, row["_row_number"])
        if record_index % workers == index:
            notices.typing_row(row["_row_number"])
            yield row
        record_index += 1


__all__ = ["TaggedRecordingContainer", "merge_ops", "split_worker"]
