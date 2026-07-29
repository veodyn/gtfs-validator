"""A temporary SQLite database holding one table per GTFS file.

Every column is nullable, including declared-required ones, because upstream
stores a row whose required field is missing rather than dropping it. Enforcing
NOT NULL here would hide exactly the rows the rules must report on.

Inserts stream. A ten-million-row stop_times.txt is the design case, so nothing
in this module may materialise a table into a list.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from gtfs_validator.schema import TableSchema
from gtfs_validator.storecodec import (
    BATCH_SIZE,
    ROW_NUMBER_COLUMN,
    SQLITE_TYPE,
    encode,
    quote_identifier,
)
from gtfs_validator.storereads import GroupedReads


class FeedStore(GroupedReads):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._schemas: dict[str, TableSchema] = {}

    @classmethod
    def open(cls, path: Path | None = None) -> FeedStore:
        """Open a store: in memory when no path is given, on disk otherwise.

        The on-disk form exists for feeds too large for RAM. The caller owns the
        file's lifetime and its directory's free space.
        """
        connection = sqlite3.connect(str(path) if path else ":memory:")
        # This database is rebuilt from the feed on every run and never survives
        # a crash, so durability buys nothing and costs a great deal of time.
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        return cls(connection)

    def __enter__(self) -> FeedStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def create_table(self, schema: TableSchema) -> None:
        columns = [f"{ROW_NUMBER_COLUMN} INTEGER NOT NULL"]
        columns.extend(
            f"{quote_identifier(field.name)} {SQLITE_TYPE.get(field.type, 'TEXT')}"
            for field in schema.fields
        )
        table = quote_identifier(schema.filename)
        self._connection.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
        self._schemas[schema.filename] = schema

    def insert_rows(self, schema: TableSchema, rows: Iterable[dict]) -> None:
        names = [ROW_NUMBER_COLUMN, *(f.name for f in schema.fields)]
        placeholders = ", ".join("?" * len(names))
        quoted = ", ".join(quote_identifier(name) for name in names)
        table = quote_identifier(schema.filename)
        # Values are bound; only identifiers are interpolated, and every one of
        # them has just passed quote_identifier.
        statement = f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})"  # noqa: S608

        batch: list[tuple] = []
        for row in rows:
            batch.append(
                (
                    row[ROW_NUMBER_COLUMN],
                    *(encode(f.type, row.get(f.name)) for f in schema.fields),
                )
            )
            if len(batch) >= BATCH_SIZE:
                self._connection.executemany(statement, batch)
                batch.clear()
        if batch:
            self._connection.executemany(statement, batch)
        self._connection.commit()

    def commit(self) -> None:
        """Commit any open implicit transaction; a no-op when there is none.

        The parallel loader needs it before DETACH, which refuses to run inside
        the transaction its own INSERT ... SELECT opened.
        """
        self._connection.commit()

    def count(self, filename: str) -> int:
        if filename not in self._schemas:
            return 0
        table = quote_identifier(filename)
        cursor = self._connection.execute(
            f"SELECT COUNT(*) FROM {table}"  # noqa: S608
        )
        return int(cursor.fetchone()[0])

    def rows(self, filename: str) -> Iterator[sqlite3.Row]:
        if filename not in self._schemas:
            return iter(())
        table = quote_identifier(filename)
        return self._connection.execute(
            f"SELECT * FROM {table} ORDER BY {ROW_NUMBER_COLUMN}"  # noqa: S608
        )

    def rows_in_range(self, filename: str, low: int, high: int) -> Iterator[sqlite3.Row]:
        """The rows whose `_row_number` lies in [low, high], in file order.

        For the parallel entity pass: contiguous ranges concatenated in ascending
        order are exactly the full-table scan, and entity rules are per-row, so a
        range boundary cannot change what any of them sees.
        """
        if filename not in self._schemas:
            return iter(())
        table = quote_identifier(filename)
        return self._connection.execute(
            f"SELECT * FROM {table} WHERE {ROW_NUMBER_COLUMN} BETWEEN ? AND ? "  # noqa: S608
            f"ORDER BY {ROW_NUMBER_COLUMN}",
            (low, high),
        )

    def row_number_bounds(self, filename: str) -> tuple[int, int] | None:
        """The smallest and largest `_row_number`, or None for an empty table."""
        if filename not in self._schemas:
            return None
        table = quote_identifier(filename)
        row = self._connection.execute(
            f"SELECT MIN({ROW_NUMBER_COLUMN}), MAX({ROW_NUMBER_COLUMN}) FROM {table}"  # noqa: S608
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return (row[0], row[1])

    def create_index(self, filename: str, column: str) -> None:
        """An index on `(column, _row_number)`, so keyed reads are seeks with no sort.

        Idempotent, and named after the table and column so two callers asking for the
        same index get one. Composite because every keyed query here orders by
        `_row_number` within the key and `rows_grouped_by` by `(column, _row_number)`:
        each becomes an index walk, where a single-column index left SQLite externally
        sorting 3.45 million shape rows once per calling rule, minutes of
        `vdbeMergeEngineStep` in a `sample` of a long run.
        """
        if filename not in self._schemas:
            return
        table = quote_identifier(filename)
        # Both identifiers come from the schema registry by way of quote_identifier; the index
        # name is derived from them and so inherits the same guarantee.
        name = quote_identifier(f"idx_{filename}_{column}".replace(".", "_"))
        self._connection.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
            f"({quote_identifier(column)}, {ROW_NUMBER_COLUMN})"
        )

    def rows_where(self, filename: str, column: str, value: object) -> Iterator[sqlite3.Row]:
        """The rows whose `column` equals `value`, in file order.

        For a rule that has to visit one key's rows at a time rather than the whole table.
        Call `create_index` for the column first, or every call scans the table.
        """
        if filename not in self._schemas:
            return iter(())
        table = quote_identifier(filename)
        return self._connection.execute(
            f"SELECT * FROM {table} WHERE {quote_identifier(column)} = ? "  # noqa: S608
            f"ORDER BY {ROW_NUMBER_COLUMN}",
            (value,),
        )

    def rows_missing_reference(
        self,
        child: str,
        column: str,
        parents: Sequence[tuple[str, str, bool]],
        *,
        skip_empty: bool = False,
    ) -> Iterator[sqlite3.Row]:
        """Child rows whose `column` names nothing in the union of the parents' columns.

        Each parent is `(filename, column, defaults_empty)`. One statement rather than a Python set
        of parent keys, because the parents include stops.stop_id and trips.trip_id: holding either
        in memory is the class of defect `tools/measure_scale.py` exists to catch, and the
        differential harness cannot see it because every probe feed is tiny.

        A parent table that does not exist contributes no keys, which is upstream's behaviour for
        an absent optional file rather than an oversight: measured on `fkv4`, where a feed with no
        shapes.txt still reports its trips' shape_id.

        `defaults_empty` reads an absent parent key as `""` rather than dropping the row, which is
        what upstream's `@Index` lookup does and what its primary key lookup does not. A parent whose
        keys are dropped also has to drop NULLs explicitly: `x NOT IN (SELECT k ...)` is NULL rather
        than true as soon as one k is NULL, so one empty key would otherwise silence the whole
        reference. See `rules/_shared/foreign_keys.Parent` for the two probes.

        `skip_empty` additionally passes over a child value of `""`, for the two validators upstream
        guards with `isEmpty()` rather than with `hasX()`.
        """
        if child not in self._schemas:
            return iter(())
        table = quote_identifier(child)
        key = quote_identifier(column)
        unions = []
        for parent, parent_column, defaults_empty in parents:
            if parent not in self._schemas:
                continue
            self.create_index(parent, parent_column)
            parent_key = quote_identifier(parent_column)
            # Both identifiers have just passed quote_identifier, which rejects anything not shaped
            # like a schema name, and no feed value reaches this string.
            source = f"FROM {quote_identifier(parent)}"
            if defaults_empty:
                unions.append(f"SELECT COALESCE({parent_key}, '') {source}")
            else:
                unions.append(f"SELECT {parent_key} {source} WHERE {parent_key} IS NOT NULL")
        known = " UNION ".join(unions)
        clause = f" AND {key} NOT IN ({known})" if known else ""
        empty = f" AND {key} != ''" if skip_empty else ""
        # Every identifier here has passed quote_identifier, and there are no bound values. The child
        # column is deliberately not indexed: the query scans it in row order, so an index on it is
        # never consulted and would be a full B-tree over stop_times.txt for nothing.
        return self._connection.execute(
            f"SELECT {ROW_NUMBER_COLUMN}, {key} AS value FROM {table} "  # noqa: S608
            f"WHERE {key} IS NOT NULL{empty}{clause} ORDER BY {ROW_NUMBER_COLUMN}"
        )

    def query(self, sql: str, params: tuple = ()) -> Iterator[sqlite3.Row]:
        return self._connection.execute(sql, params)

    def has_table(self, filename: str) -> bool:
        return filename in self._schemas

    def drop_table(self, filename: str) -> None:
        """Discard a table and forget its schema.

        Used when a loader raises partway through a file: the store may hold a
        prefix of its rows, and indexing a half-loaded table would emit
        duplicate_key notices that a complete load would not. Dropping it removes
        it from has_table so check_indexes skips it entirely.
        """
        if filename not in self._schemas:
            return
        table = quote_identifier(filename)
        self._connection.execute(f"DROP TABLE IF EXISTS {table}")
        del self._schemas[filename]

    def close(self) -> None:
        self._connection.close()
