"""The read surface a file rule receives, and the exception a failed dependency raises.

Split from `runner`, which runs the rules, when the two together passed the file-size limit.
The division is by responsibility: this file decides *what a rule may ask the store*, and it
grew when the rules stopped reading whole tables and started reading a key at a time.

Every reader here answers the same question about a table's load status before it answers
anything about rows, which is the point of having one surface rather than handing rules the
store: upstream skips a FileValidator outright when a container injected into it is unusable,
and a rule that read such a table as merely empty would report on every row of it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from gtfs_validator.schema import REQUIRED_FILES
from gtfs_validator.store import FeedStore
from gtfs_validator.table_status import TableLoad


class DependencyFailed(Exception):
    """Raised when a file rule reads a table whose load failed.

    Upstream skips a FileValidator outright when any container injected into it has a
    non-parsable status, so the rule's notices are never emitted. Reading the table as
    simply empty is a false-positive generator, and it is a mistake every rule reading a
    table can make independently: an absent stop_times.txt had four rules reporting every
    trip and every stop, and exposed a fifth, unusable_trip, that had been doing it since
    an earlier cohort.

    Raising from `rows()` makes the failure impossible to overlook, rather than something
    each rule has to remember. The runner discards whatever the rule had yielded.
    """


def as_dicts(rows: Iterator) -> Iterator[dict]:
    """`sqlite3.Row` objects as plain dicts, taking the column names once per query.

    `dict(row)` re-reads a Row's description for every row. Zipping against the names, fetched once
    from the first row, is 1.87x faster on a ten-column table, measured. That matters because this is
    the busiest generator in the process: profiling a real 997,334-row feed counted 10,567,823 rows
    through here, roughly ten full passes, since several rules each stream the same table.

    Making *fewer* passes would be worth far more than converting each row faster, and is an
    architectural change rather than this one.
    """
    iterator = iter(rows)
    first = next(iterator, None)
    if first is None:
        return
    keys = first.keys()
    yield dict(zip(keys, first, strict=True))
    for row in iterator:
        yield dict(zip(keys, row, strict=True))


class FeedView:
    """The read surface a file rule gets: whole tables, and table presence.

    Deliberately two methods. Handing every rule the store would make the rule
    layer harder to read than the Java it ports, and a rule that genuinely needs
    a join can be given more when one exists.
    """

    def __init__(
        self,
        store: FeedStore,
        loads: Mapping[str, TableLoad],
        present: frozenset[str],
    ) -> None:
        self._store = store
        self._loads = loads
        self._present = present
        # Scratch space for shared helpers to memoise per-feed derivations.
        # Upstream shares one ServiceIntervalCache between the validators that need
        # it; expanding every calendar once per rule instead was the dominant cost
        # of the service-window cohort.
        self.cache: dict[str, object] = {}
        # Which (table, column) pairs `rows_where` has already indexed, so the CREATE INDEX
        # runs once per feed rather than once per key.
        self._indexed: set[str] = set()

    def rows(self, filename: str) -> Iterator[dict]:
        """A table's rows, or nothing at all if its load failed.

        A single unparsable row marks the whole table UNPARSABLE_ROWS, and
        upstream then hands later FileValidators a container built for an invalid
        status, which holds no entities: the clean rows that did survive are
        invisible to them. Measured on a calendar.txt whose second row is short
        and whose first has every day off, where the jar reports only
        invalid_row_length and we reported the day-of-week notice too.
        """
        if self.dependency_failed(filename):
            raise DependencyFailed(filename)
        return as_dicts(self._store.rows(filename))

    def distinct_in_file_order(
        self, filename: str, column: str, require: str | None = None
    ) -> Iterator[object]:
        """A column's distinct values, ordered by first appearance. Gated like `rows`.

        For a rule keying a map on that column: the iteration-order models need the keys and
        not the rows, and asking for the keys alone is what lets the rows stay in the store.
        `require` restricts which rows count, since a caller that skips a row must not key its
        map on it either.
        """
        if self.dependency_failed(filename):
            raise DependencyFailed(filename)
        return self._store.distinct_in_file_order(filename, column, require)

    def rows_where(self, filename: str, column: str, value: object) -> Iterator[dict]:
        """One key's rows, in file order. Gated like `rows`.

        Indexes the column on first use. The index is the difference between a seek and a
        table scan per key, and building it once is invisible next to either.
        """
        if self.dependency_failed(filename):
            raise DependencyFailed(filename)
        self._ensure_index(filename, column)
        return as_dicts(self._store.rows_where(filename, column, value))

    def _ensure_index(self, filename: str, column: str) -> None:
        """Index the column once per feed rather than once per read."""
        indexed = f"{filename}:{column}"
        if indexed not in self._indexed:
            self._store.create_index(filename, column)
            self._indexed.add(indexed)

    def rows_for_keys(
        self, filename: str, column: str, values: Sequence[object]
    ) -> dict[object, list[dict]]:
        """Several keys' rows at once, in one statement. Gated and indexed like `rows_where`.

        For a rule walking every key in an order of its own: it can take them a batch at a time
        and still hold only a batch. See `FeedStore.rows_for_keys` for why the round trip
        matters.
        """
        if self.dependency_failed(filename):
            raise DependencyFailed(filename)
        self._ensure_index(filename, column)
        return self._store.rows_for_keys(filename, column, values)

    def rows_missing_reference(
        self,
        child: str,
        column: str,
        parents: Sequence[tuple[str, str, bool]],
        *,
        skip_empty: bool = False,
    ) -> Iterator[dict]:
        """Child rows failing a foreign key, in row order. Gated on the child only.

        The parents are the caller's to check. Upstream skips one FileValidator at a time when a
        container injected into it failed to parse, and foreign_key_violation stands in for about
        fifty of them, so raising for a parent would cost the other forty-nine their notices.
        """
        if self.dependency_failed(child):
            raise DependencyFailed(child)
        rows = self._store.rows_missing_reference(child, column, parents, skip_empty=skip_empty)
        return as_dicts(rows)

    def group_counts(self, filename: str, column: str) -> Iterator[tuple[object, int]]:
        """Each distinct non-null value of `column` with its row count. Gated like `rows`."""
        if self.dependency_failed(filename):
            raise DependencyFailed(filename)
        return self._store.group_counts(filename, column)

    def rows_where_any_set(
        self, filename: str, columns: Sequence[str], require: str | None = None
    ) -> Iterator[dict]:
        """The rows where any of `columns` is non-null, in file order. Gated like `rows`."""
        if self.dependency_failed(filename):
            raise DependencyFailed(filename)
        return as_dicts(self._store.rows_where_any_set(filename, columns, require))

    def rows_where_all_null(self, filename: str, columns: Sequence[str]) -> Iterator[dict]:
        """The rows where every one of `columns` is null, in file order. Gated like `rows`."""
        if self.dependency_failed(filename):
            raise DependencyFailed(filename)
        return as_dicts(self._store.rows_where_all_null(filename, columns))

    def rows_at_group_max(self, filename: str, group: str, order: str) -> Iterator[dict]:
        """Per group, the row holding the greatest `order` value. Gated like `rows`.

        The tie and null rules are the store's: last in file order among equals, and
        rows null in either column never count. For a rule that keeps one row per key
        of a large table, this returns the survivors instead of the table.
        """
        if self.dependency_failed(filename):
            raise DependencyFailed(filename)
        return as_dicts(self._store.rows_at_group_max(filename, group, order))

    def rows_grouped_by(self, filename: str, column: str) -> Iterator[tuple[object, list[dict]]]:
        """Complete groups of rows, one at a time, in the column's own order. Gated like `rows`.

        For a rule that has to see every group but does not care what order they arrive in.
        One scan rather than a seek per key; see `FeedStore.rows_grouped_by`.
        """
        if self.dependency_failed(filename):
            raise DependencyFailed(filename)
        return self._store.rows_grouped_by(filename, column)

    def entity_rows(self, filename: str) -> Iterator[dict]:
        """A table's surviving rows even when its load failed.

        The opposite gate to `rows()`, and the difference is upstream's: a
        SingleEntityValidator runs per row *during* loading, so a clean row is
        validated before a later broken row spoils the table, while a FileValidator
        runs afterwards against a container that an invalid status leaves empty.

        Measured on a fare_media.txt whose first row wants a name and whose second has
        an unparsable fare_media_type: the jar reports both invalid_integer and
        missing_recommended_field, and reading through `rows()` lost the second.

        Only for a file rule standing in for per-entity validation, which is the case
        when one notice code has both an entity-level and a file-level source.
        """
        if not self._store.has_table(filename):
            return iter(())
        return as_dicts(self._store.rows(filename))

    def dependency_failed(self, filename: str) -> bool:
        """Whether a table a rule reads is in a state that stops upstream running at all.

        `ValidatorUtil.invokeSingleFileValidators` skips a FileValidator when any injected
        container has a non-parsable status, so a rule must ask about the *status* and not
        just about the rows. Reading "no rows" as "nothing to report" is a false positive
        generator: an absent stop_times.txt made two rules report every trip and every stop,
        where the jar reports neither.

        Three states, all measured:

        - loaded and indexable, including a header-only table: the rule runs, and a valid
          empty table really does mean every trip is unused;
        - present but failed, for instance one row missing a required field: skip;
        - absent: skip only if the file is required. An optional file upstream injects as an
          empty container, which is why a feed with no location_group_stops.txt still
          reports stop_without_stop_time.
        """
        load = self._loads.get(filename)
        if load is not None and load.is_indexable and self._store.has_table(filename):
            return False
        if filename not in self._present:
            return filename in REQUIRED_FILES
        return True

    def whole_feed_failed(self) -> bool:
        """Whether any table in the feed is in a state upstream treats as a failure.

        For the validators injected with the *feed* container rather than with individual
        tables. Measured on the translations validator: a feed whose stops.txt has a short row
        reports nothing about a translations row naming feed_info, a table that loaded
        perfectly, because the container the validator depends on is the whole feed.
        """
        candidates = set(self._loads) | set(REQUIRED_FILES)
        return any(self.dependency_failed(name) for name in candidates)

    def has_column(self, filename: str, column: str) -> bool:
        """Whether the file declared the column, regardless of any value.

        `hasColumn` upstream. A header test, like requires_any_column on an entity
        rule: route_networks_specified_in_more_than_one_file fires on the presence of
        routes.network_id even when every row leaves it blank. Read from the load's
        recorded columns rather than the store, so a table that failed to load still
        answers about the header it did declare.
        """
        load = self._loads.get(filename)
        return load is not None and column in load.columns

    def is_missing(self, filename: str) -> bool:
        """Whether the *archive* lacked the file, which is neither of the above.

        Three states, not two. Upstream's isMissingFile is
        `status == MISSING_FILE`, so a table that is present but empty, and a
        table that is present but failed to load, are both "not missing" while
        holding no rows. Deriving this from the loaded tables instead reported
        missing_calendar_and_calendar_date_files for a feed whose calendar.txt was
        present but undecodable.
        """
        return filename not in self._present
