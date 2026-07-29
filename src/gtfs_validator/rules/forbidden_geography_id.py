"""StopTimesGeographyIdPresenceValidator: a stop time naming two geographies.

Exactly one of `stop_id`, `location_group_id` and `location_id` is allowed. More than
one draws this; none draws `missing_required_field` naming `stop_id`, which lives in
that code's own module.

The absent ids are **omitted** from the context rather than reported as "". Upstream
passes an explicit `null` for each one it does not have, and gson drops a null field,
so this differs from the four notices where the generated entity's String default
shows through as "". Measured: a row naming a stop and a location group reports
`stopId` and `locationGroupId` and carries no `locationId` key at all.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule

GEOGRAPHY_FIELDS = (
    ("stop_id", "stopId"),
    ("location_group_id", "locationGroupId"),
    ("location_id", "locationId"),
)


@rule(code="forbidden_geography_id", severity=Severity.ERROR, filename="stop_times.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    present = {key: row[column] for column, key in GEOGRAPHY_FIELDS if row.get(column) is not None}
    if len(present) <= 1:
        return
    yield Notice(
        "forbidden_geography_id",
        Severity.ERROR,
        {"csvRowNumber": row["_row_number"], **present},
    )
