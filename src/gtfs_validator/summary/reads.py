"""The read semantics `FeedMetadata` uses, which are not the rule layer's.

Upstream builds the summary from `feedContainer.getTableForFilename(...)` and
then calls `entityCount()` or `getEntities()` on what comes back. A container
whose file was absent, and a container whose parse failed, both hold nothing. So
the summary sees an empty table in three different situations and cannot tell
them apart, which is deliberate on upstream's side and has to be deliberate here
too: reporting `Stops: 0` for a stops.txt that failed to parse is what the jar
does.

This is the opposite of `FeedView.rows`, which raises so that a rule can decline
to run. The summary never declines; it reports zero.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.rules.feedview import DependencyFailed, FeedView


def table_rows(view: FeedView, filename: str) -> Iterator[dict]:
    """A table's rows, or nothing at all when it is absent or failed to load.

    The `DependencyFailed` catch is belt and braces rather than dead code: the
    two gates below answer from the load record and the archive listing, and
    `rows` answers from the same state a moment later. Letting the exception
    escape here would turn a malformed feed into a traceback from the *summary*,
    which is precisely the failure mode `system_errors.json` exists to avoid.
    """
    if view.is_missing(filename) or view.dependency_failed(filename):
        return iter(())
    try:
        return view.rows(filename)
    except DependencyFailed:
        return iter(())


def has(row: dict, field: str) -> bool:
    """`hasX()`: the field parsed to a value, even if that value is zero or false.

    The same test `rules/_shared/booking.has` makes, and for the same reason: an
    empty cell is absent however the header reads, so this asks the parsed value
    rather than the column. A quoted `" "` is present and empty, a bare ` ` is
    absent, and `typing_stage.type_row` has already resolved which is which.
    """
    return row.get(field) is not None


def any_record(view: FeedView, filename: str) -> bool:
    """`hasAtLeastOneRecordInFile`: the table holds at least one row."""
    return any(True for _ in table_rows(view, filename))


def any_record_with(view: FeedView, filename: str, *fields: str) -> bool:
    """`hasAtLeastOneRecordForFields`: one row has *all* of these fields set.

    Upstream's helper takes a list of conditions and requires `allMatch` on a
    single entity, so a feed setting `from_area_id` on one row and `to_area_id`
    on another does not satisfy a two-field condition. Every caller upstream
    passes exactly one condition and ORs the calls together, which is not the
    same thing, and is why the callers below spell out which they mean.
    """
    return any(all(has(row, field) for field in fields) for row in table_rows(view, filename))
