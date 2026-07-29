"""TimepointTimeValidator, first branch: a timed stop that does not say if it is exact.

A stop time carrying an arrival or a departure should say whether that time is exact,
so a blank `timepoint` on such a row is reported. Measured: the row with both times
and no timepoint is reported, and one with `timepoint` 0 and times is not.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.timepoints import STOP_TIMES, TIMEPOINT, declares_timepoint
from gtfs_validator.rules.registry import file_rule, scan_rule


class _Consumer:
    def row(self, row: dict) -> list[Notice] | None:
        has_time = row.get("arrival_time") is not None or row.get("departure_time") is not None
        if not has_time or row.get(TIMEPOINT) is not None:
            return None
        return [
            Notice(
                "missing_timepoint_value",
                Severity.WARNING,
                {
                    "csvRowNumber": row["_row_number"],
                    "tripId": row.get("trip_id"),
                    "stopSequence": row.get("stop_sequence"),
                },
            )
        ]

    def finish(self) -> Iterator[Notice]:
        return iter(())


@scan_rule(code="missing_timepoint_value", table=STOP_TIMES)
def scan(feed, ctx: Context) -> _Consumer | None:
    """The hub factory: None when the header never declares `timepoint`."""
    if not declares_timepoint(feed):
        return None
    return _Consumer()


@file_rule(code="missing_timepoint_value", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    """The sequential path, on the same consumer the hub feeds."""
    consumer = scan(feed, ctx)
    if consumer is None:
        return
    for row in feed.rows(STOP_TIMES):
        yield from consumer.row(row) or ()
    yield from consumer.finish()
