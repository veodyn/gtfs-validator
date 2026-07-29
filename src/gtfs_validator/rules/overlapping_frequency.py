"""OverlappingFrequencyValidator: two frequency windows on one trip that cover the same time.

A trip's frequencies say when its headway applies, so two windows overlapping means the feed
gives two answers for one moment. Each trip's windows are sorted by start, then end, then
headway, and each is compared with the one before it.

Three details, each measured:

- The comparison is strict, so a window may begin exactly where the previous one ends.
- Only adjacent pairs after sorting are compared, so a long window containing a short one and
  a third overlapping only the long one draws one notice rather than two.
- The headway is a real sort key. Two identical windows with headways 900 then 300 are
  reported with the *second* row as `prev`, which sorting on the times alone would not do.

The trips come out in `ArrayListMultimap` order, which is a 32-bucket table rather than a
`HashMap`'s 16. Measured on a feed whose trips are written T1, T2, T4 and reported T4, T1, T2.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import multimap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import overlap
from gtfs_validator.rules.registry import file_rule

CODE = "overlapping_frequency"
FREQUENCIES = "frequencies.txt"
HEADWAY = "headway_secs"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    groups: dict[str, list[dict]] = {}
    for row in feed.rows(FREQUENCIES):
        groups.setdefault(row.get("trip_id") or "", []).append(row)

    for trip_id in multimap_order(groups):
        for previous, current in overlap.overlapping_pairs(groups[trip_id], _sort_key):
            yield Notice(
                CODE,
                Severity.ERROR,
                {**overlap.pair_context(previous, current), "tripId": trip_id},
            )


def _sort_key(row: dict) -> tuple[int, int, int]:
    return (
        overlap.time_of(row, overlap.START),
        overlap.time_of(row, overlap.END),
        row.get(HEADWAY) or 0,
    )
