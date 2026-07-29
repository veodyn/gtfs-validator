"""ForeignKeyViolationNotice: 44 generated validators and five hand-written ones, one code.

Each reference is gated on its own tables, not on the feed. Upstream skips one FileValidator at a
time when `dependenciesHaveErrors`, so an unparsable routes.txt silences trips.route_id and leaves
stop_times.stop_id reported (probes `fkv25` and `fkv16`). Reading through `FeedView.rows` would raise
DependencyFailed and cost the other forty-nine references their notices, so the gate is asked about
explicitly and never allowed to raise.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.foreign_keys import Reference, references
from gtfs_validator.rules.registry import file_rule

CODE = "foreign_key_violation"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed: object, context: Context) -> Iterator[Notice]:
    for reference in references():
        yield from _check(feed, reference)


def _check(feed: object, reference: Reference) -> Iterator[Notice]:
    if feed.dependency_failed(reference.child_file):
        return
    # Every parent is an injected container too, so any one of them failing skips the validator.
    if any(feed.dependency_failed(parent.filename) for parent in reference.parents):
        return
    # `shouldCallValidate` is `childContainer.hasColumn(column)`: a header test, so a column present
    # and blank in every row still runs the check and finds nothing.
    if not feed.has_column(reference.child_file, reference.child_field):
        return
    parents = [
        (parent.filename, parent.column, parent.defaults_empty) for parent in reference.parents
    ]
    for row in feed.rows_missing_reference(
        reference.child_file,
        reference.child_field,
        parents,
        skip_empty=reference.skip_empty,
    ):
        yield Notice(
            code=CODE,
            severity=Severity.ERROR,
            context={
                "childFilename": reference.child_file,
                "childFieldName": reference.child_field,
                "parentFilename": reference.parent_label,
                "parentFieldName": reference.parent_field,
                "fieldValue": row["value"],
                "csvRowNumber": row["_row_number"],
            },
        )
