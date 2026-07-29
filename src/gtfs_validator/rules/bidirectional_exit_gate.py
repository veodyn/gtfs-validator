"""BidirectionalExitGateValidator: an exit gate cannot be bidirectional."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule

# GtfsPathwayMode.EXIT_GATE, and is_bidirectional 1. Both are reported as
# numbers rather than as enum names, unlike missing_stop_name's locationType.
EXIT_GATE = 7
BIDIRECTIONAL = 1


@rule(code="bidirectional_exit_gate", severity=Severity.ERROR, filename="pathways.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    mode = row.get("pathway_mode")
    bidirectional = row.get("is_bidirectional")
    if mode != EXIT_GATE or bidirectional != BIDIRECTIONAL:
        return
    yield Notice(
        "bidirectional_exit_gate",
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            "pathwayMode": mode,
            "isBidirectional": bidirectional,
        },
    )
