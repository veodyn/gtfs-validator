"""Parallel stage 5 behind `-t`, with the sequential runner's order replayed exactly.

Two phases, mirroring `runner.run_rules`:

- The **entity pass** parallelises per table. A worker streams its tables' rows past
  the applicable entity rules into an *uncapped* container per table; the main
  process replays each table's notices through `add` in `sorted(loads)` order, which
  is the sequential visit order, so the global caps recompute identically.
- **File rules** parallelise per rule. The sequential runner already buffers each
  rule into a capped container and `merge`s it in registry order; a worker returns
  exactly that container (it pickles: plain lists and dicts), or a marker for the
  DependencyFailed skip or a raised exception, and the main process merges and
  reports in registry order. Byte-identity across thread counts is the gate.

Workers open the store file read-only over a URI, so the one writer (the main
process) is finished before any of this starts.
"""

from __future__ import annotations

import sqlite3
import sys
from multiprocessing import get_context
from pathlib import Path

from gtfs_validator.context import Context
from gtfs_validator.error_ids import carry
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.rules.feedview import DependencyFailed, FeedView
from gtfs_validator.rules.parallel_partition import (
    HOT_INDEXES,
    cohort_parts,
    round_robin,
)
from gtfs_validator.rules.registry import entity_rules_for, file_rules, load_rules
from gtfs_validator.rules.runner import _applies, _report_failure
from gtfs_validator.store import FeedStore
from gtfs_validator.storecodec import ROW_NUMBER_COLUMN, quote_identifier
from gtfs_validator.table_status import TableLoad

_UNCAPPED = sys.maxsize
# The skip marker for a file rule that raised DependencyFailed: the skip is the
# behaviour, and the main process must do nothing at all for it.
_SKIPPED = "skipped"


class _ReadOnlyStore(FeedStore):
    """A worker's view of the finished store: reads only, index requests ignored.

    CREATE INDEX on a read-only connection raises, and letting it would turn an
    on-demand index into a fake rule failure. The main process pre-creates
    HOT_INDEXES; anything else falls back to a scan, which is slower and nothing
    else.
    """

    def create_index(self, filename: str, column: str) -> None:  # noqa: ARG002 - deliberate no-op
        return


def _open_readonly(store_path: str) -> FeedStore:
    connection = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
    store = _ReadOnlyStore(connection)
    # The schemas registry is rebuilt from the table names; the store only needs to
    # answer has_table and run reads, both of which work from the live database.
    store._schemas = {
        row[0]: None
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    return store


def _entity_worker(store_path, ranges, loads, ctx):
    """((table, low) -> (notices-in-order, [(spec, exception)])) for this worker's ranges.

    A range covers `_row_number` in [low, high]; low/high of None means the whole
    table. Entity rules are per-row (asserted by the module-mutable scan recorded in
    the plan notes), so contiguous ranges replayed in ascending order are exactly
    the sequential scan.
    """
    load_rules()
    results = {}
    store = _open_readonly(store_path)
    try:
        for filename, low, high in ranges:
            notices = NoticeContainer(_UNCAPPED, _UNCAPPED, _UNCAPPED)
            failures = []
            specs = [
                spec
                for spec in entity_rules_for(filename)
                if _applies(spec, loads[filename].columns)
            ]
            rows = store.rows(filename) if low is None else store.rows_in_range(filename, low, high)
            for row in rows:
                entity = dict(row)
                for spec in specs:
                    try:
                        for notice in spec.func(entity, ctx):
                            notices.add(notice)
                    except Exception as exc:  # noqa: BLE001 - replayed in the parent
                        # The spec itself travels back (it pickles: a dataclass of
                        # strings and a module-level function), so the parent
                        # reports with the same fields the sequential path uses.
                        failures.append((spec, carry(exc)))
            results[(filename, low or 0)] = (notices.in_order(), failures)
    finally:
        store.close()
    return results


def _file_worker(store_path, codes, loads, present, ctx, caps):
    """(code -> capped container | _SKIPPED | exception) for this worker's file rules."""
    load_rules()
    by_code = {spec.code: spec for spec in file_rules()}
    store = _open_readonly(store_path)
    try:
        view = FeedView(store, loads, present)
        results = {}
        for code in codes:
            produced = NoticeContainer(*caps)
            try:
                produced.add_all(by_code[code].func(view, ctx))
            except DependencyFailed:
                results[code] = _SKIPPED
            except Exception as exc:  # noqa: BLE001 - replayed in the parent
                results[code] = carry(exc)
            else:
                results[code] = produced
        return results
    finally:
        store.close()


# A table below this many rows is one range: the split exists for the giant tables
# whose single-worker entity pass was the wall clock, not for the dozens of small
# ones where per-range overhead would dominate.
_SPLIT_THRESHOLD_ROWS = 100_000


def prepare_split_indexes(store, tables) -> None:
    """A plain `_row_number` index for every table large enough to be split.

    Without it each range's `BETWEEN ... ORDER BY _row_number` is a full scan and
    sort, so P ranges cost P scans: a review read the SQLite plan and measured it.
    Main-process only; worker connections are read-only.
    """
    for name in tables:
        if store.count(name) >= _SPLIT_THRESHOLD_ROWS:
            table = quote_identifier(name)
            index = quote_identifier(f"idx_rownum_{name}".replace(".", "_"))
            store.query(f"CREATE INDEX IF NOT EXISTS {index} ON {table} ({ROW_NUMBER_COLUMN})")


def _entity_ranges(store_path: Path, tables: list[str], workers: int):
    """(table, low, high) jobs, splitting large tables into contiguous row ranges.

    Ranges partition [min, max] numerically; row numbers are dense enough that a
    gap only makes a range lighter. (None, None) means the whole table.
    """
    store = _open_readonly(str(store_path))
    try:
        ranges = []
        for name in tables:
            if not entity_rules_for(name):
                continue
            bounds = store.row_number_bounds(name)
            if bounds is None:
                ranges.append((name, None, None))
                continue
            low, high = bounds
            rows = store.count(name)
            if rows < _SPLIT_THRESHOLD_ROWS:
                ranges.append((name, None, None))
                continue
            pieces = min(workers * 2, max(2, rows // _SPLIT_THRESHOLD_ROWS))
            step = (high - low + 1) // pieces or 1
            starts = list(range(low, high + 1, step))[:pieces]
            for index, start in enumerate(starts):
                end = high if index == len(starts) - 1 else starts[index + 1] - 1
                ranges.append((name, start, end))
        return ranges
    finally:
        store.close()


def run_rules_parallel(
    store_path: Path,
    notices: NoticeContainer,
    ctx: Context,
    loads: dict[str, TableLoad],
    present: frozenset[str],
    system_errors: NoticeContainer | None,
    workers: int,
) -> None:
    """The parallel counterpart of `runner.run_rules`, byte-identical by replay."""
    load_rules()
    spawn = get_context("spawn")

    ranges = _entity_ranges(store_path, sorted(loads), workers)
    range_parts = round_robin(ranges, workers)
    code_parts = cohort_parts([spec.code for spec in file_rules()], workers)
    caps = (notices.max_total, notices.max_per_type, notices.max_exports_per_type)

    with spawn.Pool(processes=max(len(range_parts), len(code_parts), 1)) as pool:
        entity_results = pool.starmap(
            _entity_worker,
            [(str(store_path), part, loads, ctx) for part in range_parts],
        )
        file_results = pool.starmap(
            _file_worker,
            [(str(store_path), part, loads, present, ctx, caps) for part in code_parts],
        )

    merged_ranges = {}
    for result in entity_results:
        merged_ranges.update(result)
    merged_rules = {}
    for result in file_results:
        merged_rules.update(result)

    # Replays, in the sequential orders: tables sorted with each table's ranges in
    # ascending row order, then file rules in registry order, failures included at
    # their original positions.
    for key in sorted(merged_ranges):
        table_notices, failures = merged_ranges[key]
        for notice in table_notices:
            notices.add(notice)
        for spec, exc in failures:
            _report_failure(system_errors, spec, exc)
    for spec in file_rules():
        outcome = merged_rules.get(spec.code)
        if outcome is None or outcome == _SKIPPED:
            continue
        if isinstance(outcome, Exception):
            _report_failure(system_errors, spec, outcome)
            continue
        notices.merge(outcome)


__all__ = ["HOT_INDEXES", "run_rules_parallel"]
