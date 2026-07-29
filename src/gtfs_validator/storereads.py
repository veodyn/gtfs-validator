"""The FeedStore's keyed and grouped reads, split from the store when it passed the
file-size limit.

The division is by responsibility: `store.py` owns the database's lifecycle, its
tables and the plain scans; this mixin owns every read that is keyed or grouped by a
column, all of which lean on the same composite `(column, _row_number)` index that
`create_index` builds.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from gtfs_validator.storecodec import ROW_NUMBER_COLUMN, quote_identifier


class GroupedReads:
    """Mixin over the store's connection and schema registry."""

    def distinct_in_file_order(
        self, filename: str, column: str, require: str | None = None
    ) -> Iterator[object]:
        """Each distinct non-null value of `column`, ordered by where it first appears.

        The order a `HashMap` or a Guava multimap keyed on that column was populated in, which
        is what the iteration-order models need. Nulls are dropped, since a row missing a
        required column never reached upstream's container to be keyed by it.

        `require` names a second column that must also be non-null for a row to count, which
        changes both the key set and the order: a caller that skips such rows would otherwise
        key its map on a trip that contributes nothing, and put every later trip in a different
        bucket. Upstream's containers differ this way between validators, so it is a per-caller
        question rather than a default.
        """
        if filename not in self._schemas:
            return iter(())
        self.create_index(filename, column)
        table = quote_identifier(filename)
        quoted = quote_identifier(column)
        condition = f"{quoted} IS NOT NULL"
        if require is not None:
            condition += f" AND {quote_identifier(require)} IS NOT NULL"
        cursor = self._connection.execute(
            f"SELECT {quoted} FROM {table} WHERE {condition} "  # noqa: S608
            f"GROUP BY {quoted} ORDER BY MIN({ROW_NUMBER_COLUMN})"
        )
        return (row[0] for row in cursor)

    def rows_for_keys(
        self, filename: str, column: str, values: Sequence[object]
    ) -> dict[object, list[dict]]:
        """Several keys' rows at once, each key's in file order.

        One statement per batch rather than per key, which is worth a few percent rather than
        the factor a first noisy reading suggested: see `stop_time_trips.BATCH_TRIPS`, which
        carries the sweep. The caller picks the batch size and so picks how much is resident,
        and past a point a larger batch is both slower and heavier.
        """
        if filename not in self._schemas or not values:
            return {}
        table = quote_identifier(filename)
        quoted = quote_identifier(column)
        placeholders = ", ".join("?" * len(values))
        cursor = self._connection.execute(
            f"SELECT * FROM {table} WHERE {quoted} IN ({placeholders}) "  # noqa: S608
            f"ORDER BY {ROW_NUMBER_COLUMN}",
            tuple(values),
        )
        grouped: dict[object, list[dict]] = {}
        keys: list[str] | None = None
        for row in cursor:
            if keys is None:
                keys = row.keys()
            grouped.setdefault(row[column], []).append(dict(zip(keys, row, strict=True)))
        return grouped

    def group_counts(self, filename: str, column: str) -> Iterator[tuple[object, int]]:
        """Each distinct non-null value of `column` with its row count.

        For a rule that needs only a tally per key: the tally happens in SQL and one
        row per key reaches Python, instead of the whole table.
        """
        if filename not in self._schemas:
            return iter(())
        self.create_index(filename, column)
        table = quote_identifier(filename)
        quoted = quote_identifier(column)
        return self._connection.execute(
            f"SELECT {quoted}, COUNT(*) FROM {table} "  # noqa: S608
            f"WHERE {quoted} IS NOT NULL GROUP BY {quoted}"
        )

    def rows_where_any_set(
        self, filename: str, columns: Sequence[str], require: str | None = None
    ) -> Iterator[dict]:
        """The rows where at least one of `columns` is non-null, in file order.

        `require` names a column that must be non-null besides, mirroring
        `distinct_in_file_order`. For a rule whose subject is a sparse column pair,
        such as pickup and drop-off windows: the filter runs in SQL and only the
        carrying rows reach Python.
        """
        if filename not in self._schemas:
            return iter(())
        table = quote_identifier(filename)
        any_set = " OR ".join(f"{quote_identifier(column)} IS NOT NULL" for column in columns)
        condition = f"({any_set})"
        if require is not None:
            condition += f" AND {quote_identifier(require)} IS NOT NULL"
        return self._connection.execute(
            f"SELECT * FROM {table} WHERE {condition} "  # noqa: S608
            f"ORDER BY {ROW_NUMBER_COLUMN}"
        )

    def rows_where_all_null(self, filename: str, columns: Sequence[str]) -> Iterator[dict]:
        """The rows where every one of `columns` is null, in file order.

        The complement of `rows_where_any_set`, for a rule reporting rows that carry
        none of a set of alternatives; on a healthy feed that is next to no rows out
        of the largest table.
        """
        if filename not in self._schemas:
            return iter(())
        table = quote_identifier(filename)
        all_null = " AND ".join(f"{quote_identifier(column)} IS NULL" for column in columns)
        return self._connection.execute(
            f"SELECT * FROM {table} WHERE {all_null} "  # noqa: S608
            f"ORDER BY {ROW_NUMBER_COLUMN}"
        )

    def rows_at_group_max(self, filename: str, group: str, order: str) -> Iterator[dict]:
        """Per group, the whole row holding the greatest `order` value.

        Among rows sharing the greatest value, the **last in file order** wins, which is
        trip_shape_distance's measured tie rule: the container sorts stably by the
        sequence and the validator takes `get(size - 1)`. Rows where either column is
        null do not count. One SQL statement instead of streaming the whole table
        through Python to keep one row per group, which on a 1.6M-row stop_times was a
        full pass for 81k survivors.
        """
        if filename not in self._schemas:
            return iter(())
        self.create_index(filename, group)
        table = quote_identifier(filename)
        grouped = quote_identifier(group)
        ordered = quote_identifier(order)
        return self._connection.execute(
            f"SELECT t.* FROM {table} t JOIN ("  # noqa: S608
            f"  SELECT {grouped} AS g, MAX({ordered}) AS o FROM {table}"
            f"  WHERE {grouped} IS NOT NULL AND {ordered} IS NOT NULL GROUP BY {grouped}"
            f") m ON t.{grouped} = m.g AND t.{ordered} = m.o"
            f" WHERE t.{ROW_NUMBER_COLUMN} = ("
            f"  SELECT MAX(t2.{ROW_NUMBER_COLUMN}) FROM {table} t2"
            f"  WHERE t2.{grouped} = m.g AND t2.{ordered} = m.o)"
        )

    def rows_grouped_by(self, filename: str, column: str) -> Iterator[tuple[object, list[dict]]]:
        """One cursor over the whole table, yielding a complete group as each key ends.

        Cheaper than a query per key when the caller can take the groups in *any* order, since
        it is one index walk rather than a seek per key. The order here is the column's
        own, which is not the order upstream reports anything in: a caller that needs that must
        reorder what it collects. Nulls are dropped, as in `distinct_in_file_order`.

        Holds one group at a time, which is the point: the caller never sees the whole table.
        """
        if filename not in self._schemas:
            return
        self.create_index(filename, column)
        table = quote_identifier(filename)
        quoted = quote_identifier(column)
        cursor = self._connection.execute(
            f"SELECT * FROM {table} WHERE {quoted} IS NOT NULL "  # noqa: S608
            f"ORDER BY {quoted}, {ROW_NUMBER_COLUMN}"
        )
        current: object = None
        batch: list[dict] = []
        keys: list[str] | None = None
        for row in cursor:
            if keys is None:
                keys = row.keys()
            key = row[column]
            if batch and key != current:
                yield current, batch
                batch = []
            current = key
            batch.append(dict(zip(keys, row, strict=True)))
        if batch:
            yield current, batch
