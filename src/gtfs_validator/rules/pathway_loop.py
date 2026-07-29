"""PathwayLoopValidator: a pathway from a stop back to itself.

Both ends must be present *and* equal, so a pathway missing one end is another
rule's problem rather than a loop. The reported stopId is the from end, which is
the same value as the to end by the time it fires.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule


@rule(code="pathway_loop", severity=Severity.WARNING, filename="pathways.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    from_stop = row.get("from_stop_id")
    to_stop = row.get("to_stop_id")
    if from_stop is None or to_stop is None or from_stop != to_stop:
        return
    yield Notice(
        "pathway_loop",
        Severity.WARNING,
        {
            "csvRowNumber": row["_row_number"],
            "pathwayId": row.get("pathway_id"),
            "stopId": from_stop,
        },
    )
