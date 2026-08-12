"""Parallel table loading behind `-t`, invisible by construction.

Each worker process reopens the archive from its path, parses and types its share of
tables with the exact sequential code (`loading._load_table`), writes rows into its
own temporary SQLite file, and returns per-table results. The main process copies
tables across with `ATTACH` and `INSERT ... SELECT`, which moves rows at C speed
without pickling any of them, and then replays each table's notices through the real
container's `add` in canonical file-visit order.

The replay is the whole parity story. The container's caps (`max_total`,
`max_per_type`) are global running state across the sequential stream, so workers
collect into **uncapped** containers and the caps are recomputed only in the replay;
`merge()` cannot be used here because, mirroring upstream's `addAll`, it deliberately
does not re-apply them. A table whose loader raises keeps the notices it emitted
before failing and surfaces the same system error in the same position, and its rows
are simply never copied, which is the sequential `drop_table` by another route.
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from multiprocessing import get_context
from pathlib import Path

from gtfs_validator.error_ids import carry
from gtfs_validator.loading import _load_table, _system_error
from gtfs_validator.loadops import _RecordingContainer, _replay
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.schema import load_schemas
from gtfs_validator.split_load import merge_ops, split_worker
from gtfs_validator.store import FeedStore
from gtfs_validator.storecodec import quote_identifier
from gtfs_validator.table_status import TableLoad

_UNCAPPED = sys.maxsize
# A table whose uncompressed member is at least this large splits across every
# worker; below it, whole-table assignment costs less than the repeated parse.
_SPLIT_BYTES = 256 * 2**20


def _load_worker(
    archive: str, tables: list[str], db_path: str, country_code: str, caps: tuple[int, int]
) -> dict[str, tuple[TableLoad | None, list, Exception | None]]:
    """One worker's share: (load, notices-in-order, exception) per table.

    Imported and run in a spawned process, so everything here reaches the parent by
    pickling: `TableLoad`, `Notice` and ordinary exceptions all pickle. The
    container is uncapped; see the module docstring.
    """
    from gtfs_validator.container import open_feed

    schemas = load_schemas()
    results: dict[str, tuple[TableLoad | None, list, Exception | None]] = {}
    feed = open_feed(Path(archive))
    try:
        with FeedStore.open(Path(db_path)) as store:
            for name in tables:
                notices = _RecordingContainer(caps)
                try:
                    load = _load_table(feed, schemas[name], store, notices, country_code)
                except Exception as exc:  # noqa: BLE001 - carried to the parent, reported there
                    # Pre-rendered: not every exception survives pickling, and one
                    # that does not crashes the pool's result handler and hangs
                    # the whole run. See error_ids.carry.
                    results[name] = (None, notices.ops, carry(exc))
                else:
                    results[name] = (load, notices.ops, None)
    finally:
        feed.close()
    return results


def _absorb_shares(
    name: str,
    shares: list,
    feed,
    schemas: dict,
    store: FeedStore,
    caps: tuple[int, int],
    country_code: str,
) -> tuple[TableLoad | None, list, Exception | None]:
    """One split table's shares as a plan-11 `(load, ops, failure)` triple.

    A clean set of shares merges: statuses OR together (parse-level failures are
    identical in every share by construction, so the only variance is a
    typing-level UNPARSABLE_ROWS in some owner), and the tagged streams sort
    back into sequential order. A share failing is rare and the honest recovery
    is the sequential load, in-process into the main store, recorded for the
    same replay: partial notices and drop-on-failure come out exactly as cli's
    sequential loop would produce them.
    """
    if any(share[2] is not None for share in shares):
        recorder = _RecordingContainer(caps)
        try:
            load = _load_table(feed, schemas[name], store, recorder, country_code)
        except Exception as exc:  # noqa: BLE001 - reported at the replay position
            store.drop_table(name)
            return None, recorder.ops, carry(exc)
        return load, recorder.ops, None
    merged_load = shares[0][0]
    for load, _, _ in shares[1:]:
        if not load.is_indexable:
            merged_load.fail(load.status)
    return merged_load, merge_ops([share[1] for share in shares]), None


def _sizes(feed, path: Path, names: list[str]) -> dict[str, int]:
    """Uncompressed size per file, for balancing; a directory feed stats instead.

    `names` are canonical table names, which is not what the archive is keyed by
    on a feed that spells one of them Agency.txt, so each is resolved back to its
    entry first. A name with no entry balances as zero rather than raising: this
    only decides which worker gets which table.
    """
    entries = {n: feed.entry_name(n) for n in names}
    if path.is_dir():
        return {
            n: (path / e).stat().st_size if (path / e).exists() else 0 for n, e in entries.items()
        }
    with zipfile.ZipFile(path) as archive:
        known = {info.filename: info.file_size for info in archive.infolist()}
    return {n: known.get(e, 0) for n, e in entries.items()}


def load_tables_parallel(
    feed,
    path: Path,
    schemas: dict,
    store: FeedStore,
    notices: NoticeContainer,
    system_errors: NoticeContainer,
    country_code: str,
    workers: int,
) -> dict[str, TableLoad]:
    """The parallel counterpart of the sequential per-table loop in `cli._validate`.

    Returns None to demand the sequential path for an archive the split cannot
    represent. That used to include duplicate entry names, which keyed the same
    table twice and which a review measured the parallel run misattributing the
    loader error for. The container now folds a repeated name into one file the way
    upstream's ImmutableSet does, so `feed.filenames` cannot repeat and both paths
    load the same single table.
    """
    names = [n for n in feed.filenames if n in schemas]
    if not names:
        return {}
    # Largest tables first, dealt round-robin, so stop_times and shapes land on
    # different workers rather than by accident of alphabetical order.
    sizes = _sizes(feed, path, names)
    # A giant table splits across every worker instead of serialising one:
    # measured on 684-BE, the single-worker parse-and-type of stop_times.txt was
    # two thirds of the whole run at -t 6.
    split_names = [n for n in names if sizes[n] >= _SPLIT_BYTES] if workers > 1 else []
    whole_names = [n for n in names if n not in split_names]
    partitions: list[list[str]] = [[] for _ in range(min(workers, len(whole_names)) or 1)]
    for position, name in enumerate(sorted(whole_names, key=lambda n: -sizes[n])):
        partitions[position % len(partitions)].append(name)

    caps = (notices.max_total, notices.max_per_type)
    with tempfile.TemporaryDirectory(prefix="gtfs-validator-workers-") as scratch:
        jobs = [
            (
                str(path),
                partition,
                str(Path(scratch) / f"worker{index}.sqlite"),
                country_code,
                caps,
            )
            for index, partition in enumerate(partitions)
            if partition
        ]
        split_jobs = [
            (
                str(path),
                name,
                workers,
                index,
                str(Path(scratch) / f"split{position}_{index}.sqlite"),
                country_code,
                caps,
            )
            for position, name in enumerate(split_names)
            for index in range(workers)
        ]
        spawn = get_context("spawn")
        with spawn.Pool(processes=max(len(jobs), workers, 1)) as pool:
            worker_results = pool.starmap(_load_worker, jobs) if jobs else []
            split_results = pool.starmap(split_worker, split_jobs) if split_jobs else []

        merged: dict[str, tuple[TableLoad | None, list, Exception | None]] = {}
        for result in worker_results:
            merged.update(result)

        copies = [(job[2], [n for n in job[1] if merged[n][2] is None]) for job in jobs]
        for position, name in enumerate(split_names):
            shares = split_results[position * workers : (position + 1) * workers]
            merged[name] = _absorb_shares(name, shares, feed, schemas, store, caps, country_code)
            # Scratch stores copy only when every share succeeded: on the redo
            # path the rows are already in the main store, or dropped.
            if all(share[2] is None for share in shares):
                copies.extend((job[4], [name]) for job in split_jobs if job[1] == name)

        created: set[str] = set()
        for db_path, copied in copies:
            if not copied:
                continue
            store.query("ATTACH DATABASE ? AS worker", (db_path,))
            try:
                for name in copied:
                    if name not in created:
                        store.create_table(schemas[name])
                        created.add(name)
                    table = quote_identifier(name)
                    store.query(
                        f"INSERT INTO main.{table} SELECT * FROM worker.{table}"  # noqa: S608
                    )
            finally:
                # DETACH inside the implicit transaction the INSERT opened raises
                # "database worker is locked"; the copy is complete, so commit first.
                # The DETACH still runs when the commit itself raises, so a failing
                # disk cannot leave the scratch database attached past its
                # directory's lifetime.
                try:
                    store.commit()
                finally:
                    store.query("DETACH DATABASE worker")

    loads: dict[str, TableLoad] = {}
    # The replay: canonical file-visit order, through `add`, exactly as the
    # sequential loop emitted them table by table.
    for name in feed.filenames:
        if name not in merged:
            continue
        load, ops, failure = merged[name]
        _replay(notices, ops)
        if failure is not None:
            _system_error(system_errors, name, failure)
        else:
            loads[name] = load
    return loads
