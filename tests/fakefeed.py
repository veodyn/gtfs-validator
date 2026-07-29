"""A stand-in for the FeedView a file rule receives.

One definition rather than one per test module: it grew a `cache` attribute when
the shared calendar helpers started memoising per feed, and five copies all needed
the same change. A test double that drifts from the real surface stops testing the
thing it stands in for.
"""

from __future__ import annotations

from gtfs_validator.rules.runner import DependencyFailed


class FakeFeed:
    def __init__(
        self, tables: dict[str, list[dict]], unindexable: frozenset[str] = frozenset()
    ) -> None:
        self._tables = tables
        # Tables whose load failed. FeedView.rows() hides those from a file rule while
        # entity_rows() still yields them, and that difference is behaviour a rule can
        # get wrong: naming it here lets a unit test pin which reader a rule uses.
        self._unindexable = unindexable
        # FeedView.cache: scratch space for shared helpers to memoise derivations.
        self.cache: dict[str, object] = {}

    def rows(self, filename: str):
        """Raises for a failed table, as the real `FeedView.rows()` does.

        This returned an empty iterator until it was noticed that the two are not the same
        thing. For a rule reading one table the outcome coincides, which is why it went
        unnoticed: raise or return nothing, the rule reports nothing either way. For a rule
        reading two, where one failed, they differ completely. The double let such a rule
        emit the notices it derived from the healthy table, while the engine catches the
        exception and discards the rule's entire output. A unit test could therefore pass on
        a rule the engine silences.
        """
        if filename in self._unindexable:
            raise DependencyFailed(filename)
        return iter(self._tables.get(filename, []))

    def entity_rows(self, filename: str):
        return iter(self._tables.get(filename, []))

    def distinct_in_file_order(self, filename: str, column: str, require: str | None = None):
        """The column's distinct non-null values, first appearance first. Gated like `rows`.

        `dict.fromkeys` over the rows in order, which is what the real reader's
        `GROUP BY ... ORDER BY MIN(_row_number)` produces. `require` names a second column that
        must also be set, which changes the key set and therefore the bucket order.
        """
        if filename in self._unindexable:
            raise DependencyFailed(filename)
        rows = [
            row
            for row in self._tables.get(filename, [])
            if row.get(column) is not None and (require is None or row.get(require) is not None)
        ]
        return iter(dict.fromkeys(row[column] for row in rows))

    def rows_where(self, filename: str, column: str, value: object):
        """One key's rows, in file order. Gated like `rows`.

        The real reader indexes the column and seeks; here a filter is the same answer. The
        double deliberately does not model the index, since a rule cannot observe one.
        """
        if filename in self._unindexable:
            raise DependencyFailed(filename)
        rows = self._tables.get(filename, [])
        return iter([row for row in rows if row.get(column) == value])

    def rows_for_keys(self, filename: str, column: str, values):
        """Several keys' rows at once, each key's in file order. Gated like `rows`.

        A key with no rows is *absent* from the result rather than present with an empty list,
        which is what a `GROUP BY` over a query returning nothing gives, and the difference is
        what `stream_in_order` has to cope with.
        """
        if filename in self._unindexable:
            raise DependencyFailed(filename)
        wanted = set(values)
        grouped: dict[object, list[dict]] = {}
        for row in self._tables.get(filename, []):
            if row.get(column) in wanted:
                grouped.setdefault(row[column], []).append(row)
        return grouped

    def rows_missing_reference(self, child: str, column: str, parents, *, skip_empty=False):
        """The double for the store's anti-join, in row order.

        Written out rather than delegated, because the double holds dicts and not a database. The
        behaviours it has to keep are the ones the SQL was written for: an absent value is not a
        violation, the parents are a union, a parent table that is not here contributes no keys, and
        an `@Index` parent reads an absent key as the empty string while a primary key does not.
        """
        if self.dependency_failed(child):
            raise DependencyFailed(child)
        known = set()
        for parent, parent_column, defaults_empty in parents:
            for row in self._tables.get(parent, []):
                value = row.get(parent_column)
                if value is None:
                    if defaults_empty:
                        known.add("")
                    continue
                known.add(value)
        for row in self._tables.get(child, []):
            value = row.get(column)
            if value is None or (skip_empty and value == ""):
                continue
            if value not in known:
                yield {"_row_number": row["_row_number"], "value": value}

    def group_counts(self, filename: str, column: str):
        """Each distinct non-null value with its row count. Gated like `rows`."""
        if filename in self._unindexable:
            raise DependencyFailed(filename)
        counts: dict[object, int] = {}
        for row in self._tables.get(filename, []):
            key = _stored(row.get(column))
            if key is not None:
                counts[key] = counts.get(key, 0) + 1
        yield from counts.items()

    def rows_where_any_set(self, filename: str, columns, require: str | None = None):
        """Rows where any of `columns` is non-null, in file order. Gated like `rows`."""
        if filename in self._unindexable:
            raise DependencyFailed(filename)
        for row in self._tables.get(filename, []):
            if require is not None and _stored(row.get(require)) is None:
                continue
            if any(_stored(row.get(column)) is not None for column in columns):
                yield row

    def rows_where_all_null(self, filename: str, columns):
        """Rows where every one of `columns` is null, in file order. Gated like `rows`."""
        if filename in self._unindexable:
            raise DependencyFailed(filename)
        for row in self._tables.get(filename, []):
            if all(_stored(row.get(column)) is None for column in columns):
                yield row

    def rows_at_group_max(self, filename: str, group: str, order: str):
        """Per group, the row with the greatest `order` value. Gated like `rows`.

        The real store's rules exactly: the last in file order wins a tie, and a row
        null in either column never counts.
        """
        if filename in self._unindexable:
            raise DependencyFailed(filename)
        best: dict[object, dict] = {}
        for row in self._tables.get(filename, []):
            key, value = _stored(row.get(group)), _stored(row.get(order))
            if key is None or value is None:
                continue
            current = best.get(key)
            if current is None or value >= current[order]:
                best[key] = row
        yield from best.values()

    def rows_grouped_by(self, filename: str, column: str):
        """Complete groups, one at a time. Gated like `rows`.

        Grouped by the *column's* order rather than by first appearance, because that is the
        order the real reader gives and a caller relying on the other one has to be caught
        here rather than by a differential. Rows with no value for the column are dropped.
        """
        if filename in self._unindexable:
            raise DependencyFailed(filename)
        grouped: dict[object, list[dict]] = {}
        for row in self._tables.get(filename, []):
            if row.get(column) is not None:
                grouped.setdefault(row[column], []).append(row)
        return iter(sorted(grouped.items()))

    def has_column(self, filename: str, column: str) -> bool:
        """True when any row of the fake table carries the key.

        The real FeedView reads the recorded header, which a dict-of-rows double has
        no equivalent of; a row's keys are the closest stand-in. A test that needs a
        declared-but-always-empty column can pass a row with the key set to None.
        """
        return any(column in row for row in self._tables.get(filename, []))

    def is_missing(self, filename: str) -> bool:
        return filename not in self._tables

    def whole_feed_failed(self) -> bool:
        """Any listed-unindexable table stands in for the feed container being unusable.

        The validators injected with the whole feed rather than with named tables read this,
        so a test makes one table fail and expects the rule to say nothing.
        """
        return bool(self._unindexable)

    def dependency_failed(self, filename: str) -> bool:
        """A table listed as unindexable stands in for a load that failed.

        The real FeedView also treats an absent *required* file as a failure. A double that
        knew which files are required would duplicate the schema, so a test wanting that
        case lists the file as unindexable without supplying rows.
        """
        return filename in self._unindexable


def _stored(value: object) -> object:
    """What the real store would hold for this value: a bound NaN becomes NULL.

    SQLite has no NaN REAL, so the adapter stores None, and every `IS NOT NULL`
    filter in the real reads drops the row. A review measured the double keeping a
    NaN row the store excluded; this keeps the SQL-shaped doubles honest.
    """
    if isinstance(value, float) and value != value:
        return None
    return value
