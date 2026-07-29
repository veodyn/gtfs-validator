"""The interval scan two validators share: sort a group, compare adjacent pairs.

`OverlappingFrequencyValidator` and `TimeframeOverlapValidator` are the same algorithm over
different tables. Both sort each group by start then end, then walk it once comparing each row
with the one before it, and report where `curr.start < prev.end`.

Adjacent pairs, not every pair, and the difference is observable: three windows of
08:00-12:00, 09:00-10:00 and 11:00-13:00 draw one notice from the jar rather than two, because
after sorting, the third is only ever compared with the second, which it does not overlap.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from itertools import pairwise

from gtfs_validator.rules._shared.render import hhmmss

START = "start_time"
END = "end_time"


def time_of(row: dict, column: str) -> int:
    """The stored seconds, or zero for an unset column.

    `GtfsTime`'s default, not an absence: two timeframes leaving both times blank are a group
    of two zero-length windows at midnight, which the jar compares and finds do not overlap.
    """
    return row.get(column) or 0


def overlapping_pairs(
    rows: Iterable[dict], sort_key: Callable[[dict], tuple]
) -> Iterator[tuple[dict, dict]]:
    ordered = sorted(rows, key=sort_key)
    for previous, current in pairwise(ordered):
        if time_of(current, START) < time_of(previous, END):
            yield previous, current


def pair_context(previous: dict, current: dict) -> dict:
    """The four keys both notices open with, in gson's field order."""
    return {
        "prevCsvRowNumber": previous["_row_number"],
        "prevEndTime": hhmmss(time_of(previous, END)),
        "currCsvRowNumber": current["_row_number"],
        "currStartTime": hhmmss(time_of(current, START)),
    }
