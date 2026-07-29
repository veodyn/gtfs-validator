"""AttributionWithoutRoleValidator: at least one role must be assigned."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule

# GtfsAttributionRole.ASSIGNED
ASSIGNED = 1
ROLE_FIELDS = ("is_producer", "is_operator", "is_authority")


@rule(
    code="attribution_without_role",
    severity=Severity.WARNING,
    filename="attributions.txt",
    requires_any_column=ROLE_FIELDS,
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if any(row.get(field) == ASSIGNED for field in ROLE_FIELDS):
        return
    yield Notice(
        "attribution_without_role",
        Severity.WARNING,
        {
            "csvRowNumber": row["_row_number"],
            # attribution_id is optional, and the generated entity returns the
            # String default rather than null for an absent one. Measured: the
            # jar reports "" for a row that leaves it blank, so this is not a
            # case of gson dropping a null field.
            "attributionId": row.get("attribution_id") or "",
        },
    )
