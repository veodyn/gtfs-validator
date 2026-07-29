"""Stages 1 through 5 for one feed, and the summary read that has to happen inside them.

Split out of `cli` when the flag surface grew: the CLI's job is arguments, exit
codes and files, and this is the run itself. Nothing here knows what a flag is.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from gtfs_validator.container import GEOJSON_FILE, open_feed
from gtfs_validator.context import Context
from gtfs_validator.indexing import check_indexes
from gtfs_validator.loading import _load_geojson, _load_table, _system_error
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.rules.feedview import FeedView
from gtfs_validator.rules.runner import run_rules
from gtfs_validator.schema import load_schemas
from gtfs_validator.store import FeedStore
from gtfs_validator.summary import FeedFacts, Register, feed_facts
from gtfs_validator.table_status import TableLoad


def run_validation(
    path: Path,
    notices: NoticeContainer,
    system_errors: NoticeContainer,
    country_code: str = "",
    validation_date: date | None = None,
    threads: int = 1,
    register: Register | None = None,
) -> tuple[FeedFacts | None, bool]:
    """Validate one feed. Returns the summary's feed half and whether the archive opened.

    The second element is what decides the exit code. Upstream returns a
    non-SUCCESS status only from the branch where it could not open the feed at
    all, so a table that fails after the archive opened still exits 0 with the
    failure recorded in system_errors.json. Measured against the jar: a missing
    file and a corrupt zip both exit 255, a feed that opens exits 0.

    Opening the feed is inside the guard on purpose: a missing file or a
    truncated archive is a runtime failure, and upstream still writes both
    reports for it rather than dying with a traceback.
    """
    try:
        feed = open_feed(path)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        _system_error(system_errors, str(path), exc)
        return (None, False)

    schemas = load_schemas()
    facts: FeedFacts | None = None
    try:
        feed.walk(notices)
        # An on-disk store keeps a multi-million-row stop_times.txt off the heap;
        # only the batch buffer stays in memory. The file lives in a temp dir that
        # is removed when the context exits. Setting the store up can fail (an
        # unwritable TMPDIR, a full temp filesystem); that is a runtime failure and
        # must still write both reports rather than exit with a traceback, so the
        # whole block is guarded.
        with (
            tempfile.TemporaryDirectory(prefix="gtfs-validator-") as work,
            FeedStore.open(Path(work) / "feed.sqlite") as store,
        ):
            loads = _load_all(
                feed, path, schemas, store, notices, system_errors, country_code, threads
            )
            check_indexes(store, schemas, notices, loads)
            if register is not None:
                register.register("load_tables")
            # date.today is the default only. Upstream's DateForValidation is
            # settable so a run is reproducible.
            ctx = Context(date=validation_date, country_code=country_code)
            # Presence comes from the archive rather than from the tables that
            # loaded: a file that raised is absent from `loads` while still
            # being present in the feed.
            #
            # `filenames` is the .txt subset, so locations.geojson has to be added by
            # name or every rule asking `is_missing` about it is told yes on a feed that
            # carries one. That silenced overlapping_zone_and_pickup_drop_off_window
            # completely, and the unit tests could not see it: a FakeFeed answers
            # `is_missing` from the tables it was handed.
            present = frozenset(feed.filenames) | ({GEOJSON_FILE} & set(feed.root_files))
            _run(store, work, notices, ctx, loads, present, system_errors, threads)
            if register is not None:
                register.register("run_rules")
            # The summary reads the tables, so it happens before the store closes
            # with the enclosing `with`. Upstream builds FeedMetadata at the same
            # point, straight after loadAndValidate returns.
            #
            # summary.files is the whole archive listing, including files GTFS
            # does not define (a feed carrying notes.md lists it), so this reads
            # root_files rather than the .txt subset `present` holds.
            listing = frozenset(feed.root_files) | present
            facts = feed_facts(FeedView(store, loads, present), listing)
            if register is not None:
                register.register("load_and_validate")
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        _system_error(system_errors, str(path), exc)
    finally:
        feed.close()
    return (facts, True)


def _load_all(
    feed,
    path: Path,
    schemas,
    store: FeedStore,
    notices: NoticeContainer,
    system_errors: NoticeContainer,
    country_code: str,
    threads: int,
) -> dict[str, TableLoad]:
    """Stage 2 and 3 for every table, by whichever path the thread count selects."""
    loads: dict[str, TableLoad] | None = None
    if threads > 1:
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
    if GEOJSON_FILE in feed.root_files:
        try:
            loads[GEOJSON_FILE] = _load_geojson(feed, notices, store)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            _system_error(system_errors, GEOJSON_FILE, exc)
    return loads


def _run(
    store: FeedStore,
    work: str,
    notices: NoticeContainer,
    ctx: Context,
    loads: dict[str, TableLoad],
    present: frozenset[str],
    system_errors: NoticeContainer,
    threads: int,
) -> None:
    """Stage 5, sequential or split across workers."""
    if threads <= 1:
        run_rules(store, notices, ctx, loads, present, system_errors)
        return
    # Workers read the store file directly; their connections are read-only, so
    # the hot indexes are built here first and the replayed merge keeps the
    # report byte-identical (the diff_across_threads gate holds it to that).
    from gtfs_validator.rules.parallel_runner import (
        HOT_INDEXES,
        prepare_split_indexes,
        run_rules_parallel,
    )

    for index_table, index_column in HOT_INDEXES:
        store.create_index(index_table, index_column)
    prepare_split_indexes(store, sorted(loads))
    store.commit()
    run_rules_parallel(
        Path(work) / "feed.sqlite", notices, ctx, loads, present, system_errors, threads
    )
