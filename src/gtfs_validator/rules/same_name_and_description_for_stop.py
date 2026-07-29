"""StopNameValidator, second branch: a description that repeats the name."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javatext import equals_ignore_case
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule


@rule(
    code="same_name_and_description_for_stop",
    severity=Severity.WARNING,
    filename="stops.txt",
    requires_any_column=("stop_name", "location_type"),
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    name = row.get("stop_name")
    description = row.get("stop_desc")
    if name is None or description is None:
        return
    # equalsIgnoreCase rather than casefold equality; see javatext.
    if not equals_ignore_case(description, name):
        return
    yield Notice(
        "same_name_and_description_for_stop",
        Severity.WARNING,
        {
            "csvRowNumber": row["_row_number"],
            "stopId": row["stop_id"],
            "stopDesc": description,
        },
    )
