"""StopAccessValidator: a platform outside any station claiming a pathway answer.

`stop_access` describes how a place is reached *within* a station, so a platform with no parent
station has nothing for it to describe. Its counterpart is
`stop_access_specified_for_incorrect_location`, which fires for anything that is not a platform.

The two are mutually exclusive but *not* exhaustive, and this docstring first said "exactly one of
the two can apply", which is wrong twice over: a platform inside a station draws neither, and nor
does any row leaving `stop_access` unset.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import STOP, location_type_of
from gtfs_validator.rules._shared.stop_access import STOP_ACCESS, context_for
from gtfs_validator.rules.registry import rule

CODE = "stop_access_specified_for_stop_with_no_parent_station"


@rule(
    code=CODE,
    severity=Severity.ERROR,
    filename="stops.txt",
    requires_any_column=(STOP_ACCESS,),
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if row.get(STOP_ACCESS) is None or location_type_of(row) != STOP:
        return
    # `!entity.hasParentStation()`, so an empty one counts as having a station and this
    # returns. Truthiness reported a stop the jar is silent about.
    if row.get("parent_station") is not None:
        return
    yield Notice(CODE, Severity.ERROR, context_for(row, STOP))
