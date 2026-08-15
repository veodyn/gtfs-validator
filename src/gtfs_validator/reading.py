"""Load a feed and read it, without running any rule.

Stages 1 through 3 and then stop. `run_validation` has always composed exactly
this and gone on to index, run rules and build the summary, closing the store on
its way out, so nothing outside this package could load a feed and look at the
result. That is the whole of what a caller validating *against* a static feed
needs: the GTFS-Realtime validator resolves realtime trip and stop ids against
these tables and has no use for the notices, though it is better off knowing
they exist before it blames the realtime data for a broken static feed.

`load_tables` lives here rather than in `pipeline` so that both entry points
share one loading path. Two would drift, and the one nobody runs the
differentials against would drift first.

`open_raw_view` is the second read surface, and it is deliberately not the first
one with the typing turned off. It answers with the CSV's own text and never
withholds a table, which is what a caller reproducing a *lenient* reader needs:
org.onebusaway's GtfsReader, the one MobilityData's GTFS-Realtime validator
loads its static feed with, types nothing, validates nothing, and has no notion
of a table that failed. Reading a feed through the strict path and hoping is not
the same thing, because the strict path's answer for such a feed is no rows at
all. See `RawView` for what this costs a caller in exchange.
"""

from __future__ import annotations

import tempfile
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from gtfs_validator.container import GEOJSON_FILE, FeedContainer, open_feed
from gtfs_validator.csvparse import parse_table
from gtfs_validator.loading import _load_geojson, _load_table, _system_error
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.rules.feedview import FeedView
from gtfs_validator.schema import load_schemas
from gtfs_validator.store import FeedStore
from gtfs_validator.table_status import TableLoad


@dataclass(frozen=True)
class LoadedFeed:
    """One loaded feed, valid only inside the `open_feed_view` block.

    `notices` and `system_errors` hold what loading found on the way past. They
    are the same containers `run_validation` fills, minus everything the rule
    layer would have added, so a caller can tell a feed that failed to load from
    one that merely has no rows.
    """

    view: FeedView
    notices: NoticeContainer
    system_errors: NoticeContainer
    tables: frozenset[str]


def load_tables(
    feed,
    path: Path,
    schemas,
    store: FeedStore,
    notices: NoticeContainer,
    system_errors: NoticeContainer,
    country_code: str,
    threads: int,
    wanted: Collection[str] | None = None,
) -> dict[str, TableLoad]:
    """Stage 2 and 3 for every table, by whichever path the thread count selects.

    `wanted` restricts loading to the named tables. It forces the sequential
    path, because the parallel loader splits the archive by size across workers
    and has no way to express a subset; a caller asking for seven tables is not
    the caller with a multi-million-row feed to get through.
    """
    loads: dict[str, TableLoad] | None = None
    if threads > 1 and wanted is None:
        # The parallel path is opt-in and must be invisible:
        # tools/diff_across_threads.sh holds it to byte-identical reports. None
        # demands the sequential path for an archive the split cannot represent
        # (duplicate entry names).
        from gtfs_validator.parallel_load import load_tables_parallel

        loads = load_tables_parallel(
            feed, path, schemas, store, notices, system_errors, country_code, threads
        )
    if loads is None:
        loads = {}
        for filename in feed.filenames:
            if wanted is not None and filename not in wanted:
                continue
            schema = schemas.get(filename)
            if schema is None:
                continue  # unknown_file already fired in stage 1
            try:
                loads[filename] = _load_table(feed, schema, store, notices, country_code)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                # The loader raised partway through, so the store may hold a
                # prefix of this table. Drop it: indexing a half-loaded table
                # would emit duplicate_key notices a full load would not.
                store.drop_table(filename)
                loads.pop(filename, None)
                _system_error(system_errors, filename, exc)
    # locations.geojson is not a .txt table, so it is loaded on its own path. Its
    # TableLoad joins the same map, so a file that ends UNPARSABLE_ROWS looks
    # empty to a file rule exactly as a CSV table in that state does.
    if GEOJSON_FILE in feed.entry_of and (wanted is None or GEOJSON_FILE in wanted):
        try:
            loads[GEOJSON_FILE] = _load_geojson(feed, notices, store)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            _system_error(system_errors, GEOJSON_FILE, exc)
    return loads


@contextmanager
def open_feed_view(
    path: Path,
    *,
    tables: Collection[str] | None = None,
    country_code: str = "",
    threads: int = 1,
) -> Iterator[LoadedFeed]:
    """Open a feed, load its tables, and yield a read surface over them.

    The temporary SQLite database and the archive are owned by this context and
    both are gone when it exits, so the yielded `FeedView` must not outlive the
    block. A caller needing the data afterwards copies what it needs out first.

    `tables` names the files to load, defaulting to all of them. Asking a view
    about a table that was present in the archive but left unloaded raises
    `DependencyFailed` rather than reading as empty, because `FeedStore.rows`
    answers an unregistered table with an empty iterator and "no stop times" and
    "stop times were never loaded" are not the same answer.
    """
    wanted = None if tables is None else frozenset(tables)
    notices = NoticeContainer()
    system_errors = NoticeContainer()
    schemas = load_schemas()
    feed = open_feed(path)
    try:
        feed.walk(notices)
        with (
            tempfile.TemporaryDirectory(prefix="gtfs-validator-") as work,
            FeedStore.open(Path(work) / "feed.sqlite") as store,
        ):
            loads = load_tables(
                feed, path, schemas, store, notices, system_errors, country_code, threads, wanted
            )
            yield LoadedFeed(
                view=FeedView(store, loads, frozenset(feed.entry_of)),
                notices=notices,
                system_errors=system_errors,
                tables=frozenset(loads),
            )
    finally:
        feed.close()


class RawView:
    """One archive's cells as text, for a caller that does its own typing.

    The opposite of `FeedView` in every way that matters. Nothing is typed,
    nothing is range-checked, nothing is mapped to an enum, no notice is
    produced and no table is ever withheld: a row that costs the strict path the
    whole of its table is a row like any other here, because a reader holding no
    schema has no cell it can refuse. `40.7` comes back as `"40.7"` and a blank
    cell as `""`, since deciding that a blank means null belongs to whichever
    model the caller is reproducing.

    What the caller gives up is everything the schema buys: the strict path's
    notices, its `dependency_failed`, and any assurance that a column holds what
    its name suggests. This is a read surface for reproducing another reader,
    not a shortcut around validation.

    Two things are still the parser's rather than the file's, and both are
    upstream's own behaviour rather than a convenience. An unquoted field loses
    its surrounding whitespace, which is what univocity does and what onebusaway
    therefore sees. A row whose length disagrees with the header is dropped, and
    so is a row past the billionth.
    """

    def __init__(self, feed: FeedContainer, tables: frozenset[str] | None) -> None:
        self._feed = feed
        self._wanted = tables
        #: The tables this view will read: the caller's list, or every `.txt`
        #: table the archive carries when it asked for no list.
        self.tables = frozenset(feed.filenames) if tables is None else tables

    def rows(self, filename: str) -> Iterator[dict[str, str]]:
        """Every row of one table, keyed by the header's own column names.

        Each row carries `_row_number`, numbered exactly as the strict path
        numbers it: by physical line, 1-based including the header, so the first
        data row is 2. That is what lets a caller line the two reads up.

        A table the archive does not carry reads as no rows, because an absent
        optional file and an empty one are the same thing to a reader with no
        schema. A table outside an explicit `tables` raises `KeyError` instead,
        since asking for one is a mistake in the caller rather than a fact about
        the feed. A view opened for every table restricts nothing and so never
        raises here.
        """
        if self._wanted is not None and filename not in self._wanted:
            raise KeyError(f"{filename} was not among the tables this view was opened for")
        if not self._feed.is_readable(filename):
            return iter(())
        # The notices are computed and dropped rather than never computed: they
        # are the strict path's opinion about a file this surface has none about,
        # and `parse_table` is the only reader that reproduces univocity's
        # quoting, its BOM handling and its column cap.
        return parse_table(
            self._feed,
            filename,
            NoticeContainer(),
            stop_on_header_errors=False,
        )

    def is_missing(self, filename: str) -> bool:
        """Whether the archive lacks the file, as `FeedView.is_missing` reports it."""
        return filename not in self._feed.entry_of


@contextmanager
def open_raw_view(
    path: Path,
    *,
    tables: Collection[str] | None = None,
) -> Iterator[RawView]:
    """Open a feed and yield an untyped read surface over its tables.

    The archive is owned by this context and is closed when the block exits, so
    the yielded `RawView` must not outlive it. There is no store and no
    temporary database: rows are streamed from the archive on each call to
    `rows`, so reading a table twice reads the file twice.

    `tables` names the files the view will answer for, defaulting to every table
    the archive carries. Unlike `open_feed_view` it costs nothing to widen: no
    table is read until it is asked for.
    """
    feed = open_feed(path)
    try:
        yield RawView(feed, None if tables is None else frozenset(tables))
    finally:
        feed.close()
