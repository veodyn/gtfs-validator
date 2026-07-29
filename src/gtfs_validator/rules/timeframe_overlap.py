"""TimeframeOverlapValidator: two timeframes of one group and service covering the same time.

The same scan as overlapping_frequency next door, with two differences that matter.

The key is the pair (timeframe_group_id, service_id), and neither component is an absence when
the column is blank: `timeframe_group_id` is optional and its unset value is `""`, so two rows
leaving it out are one group and their overlap is reported with `timeframeGroupId: ""`.
Likewise an unset time is `GtfsTime`'s zero rather than a reason to skip the row.

The groups come out in `Collectors.groupingBy` order over an `@AutoValue` key, not in file
order. Measured on `tfov`, where the empty-group overlap is reported before the G1 overlap
although G1's rows come first. The two known limits of that model, `computeIfAbsent` and a
treeified bin of non-comparable keys, are measured against the pinned JDK. The second is
reachable from a feed: eleven group ids built from `Aa` and `BB` share one hash, and both sides
then report the same eleven notices in different orders.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import auto_value_hash, grouping_by_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import overlap
from gtfs_validator.rules.registry import file_rule

CODE = "timeframe_overlap"
TIMEFRAMES = "timeframes.txt"
GROUP_ID = "timeframe_group_id"
SERVICE_ID = "service_id"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in feed.rows(TIMEFRAMES):
        key = (row.get(GROUP_ID) or "", row.get(SERVICE_ID) or "")
        groups.setdefault(key, []).append(row)

    for key in grouping_by_order(groups, auto_value_hash):
        group_id, service_id = key
        for previous, current in overlap.overlapping_pairs(groups[key], _sort_key):
            yield Notice(
                CODE,
                Severity.ERROR,
                {
                    **overlap.pair_context(previous, current),
                    "timeframeGroupId": group_id,
                    "serviceId": service_id,
                },
            )


def _sort_key(row: dict) -> tuple[int, int]:
    # Two keys, not three: this validator has no headway to break a tie with, so two rows with
    # identical times keep the order the grouping gave them.
    return (overlap.time_of(row, overlap.START), overlap.time_of(row, overlap.END))
