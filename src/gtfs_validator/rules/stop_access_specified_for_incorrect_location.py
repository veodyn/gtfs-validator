"""StopAccessValidator: `stop_access` on something that is not a platform.

A station, entrance, node or boarding area is part of the structure a platform sits in, not a place
whose accessibility the field describes. Its counterpart is
`stop_access_specified_for_stop_with_no_parent_station`, which covers the platform case.

The two are mutually exclusive but *not* exhaustive, and this docstring first said "exactly one of
the two can apply", which is wrong twice over: a platform inside a station draws neither, and nor
does any row leaving `stop_access` unset. This rule's own fixture contains the first case.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import STOP, location_type_of
from gtfs_validator.rules._shared.stop_access import STOP_ACCESS, context_for
from gtfs_validator.rules.registry import rule

CODE = "stop_access_specified_for_incorrect_location"


@rule(
    code=CODE,
    severity=Severity.ERROR,
    filename="stops.txt",
    requires_any_column=(STOP_ACCESS,),
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    location_type = location_type_of(row)
    if row.get(STOP_ACCESS) is None or location_type == STOP:
        return
    yield Notice(CODE, Severity.ERROR, context_for(row, location_type))
