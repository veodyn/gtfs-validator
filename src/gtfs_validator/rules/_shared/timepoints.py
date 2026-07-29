"""The gate TimepointTimeValidator's two notices share.

Both return without looking at a single row unless `stop_times.txt` declares a
`timepoint` column. Legacy feeds omit it entirely, and upstream deliberately says
nothing about their missing times: the absent column is the header tests' business,
not this validator's. Sharing the gate keeps the two modules from disagreeing about it.
"""

from __future__ import annotations

STOP_TIMES = "stop_times.txt"
TIMEPOINT = "timepoint"
# GtfsStopTimeTimepoint.EXACT.
EXACT = 1


def declares_timepoint(feed) -> bool:
    return feed.has_column(STOP_TIMES, TIMEPOINT)
