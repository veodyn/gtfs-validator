"""MissingTripEdgeValidator: a trip whose first or last stop has no time.

The edges are the lowest and highest **stop_sequence**, not the first and last rows
in the file. The container indexes stop times by (trip_id, stop_sequence), so
`byTripIdMap` hands the validator a sequence-ordered list. Measured on a trip whose
rows appear as sequence 3, 1, 2: the notices name sequence 1 on row 3 and sequence 3
on row 2, so reading file order would have blamed the wrong rows.

An interior stop needs no times at all, and an edge carrying a pickup or drop-off
window is exempt: a demand-responsive stop has a window instead of a timetable.

Trips come out in `multimap_order`, because upstream iterates
`Multimaps.asMap(stopTimeTable.byTripIdMap()).entrySet()`. That is a correctness
fix with **no observable effect**, and saying so is more useful than implying one:
this code emits at most four notices per trip, two edges times two time fields, so
reaching the 1,000-sample cap needs at least 250 trips, and by 250 keys a
16-bucket table and a 32-bucket one have both resized to 512 and agree exactly.
The order is right because the collection is right, not because a probe caught it.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import multimap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import stop_time_trips
from gtfs_validator.rules.registry import file_rule

WINDOW_FIELDS = ("start_pickup_drop_off_window", "end_pickup_drop_off_window")
EDGE_FIELDS = ("arrival_time", "departure_time")


@file_rule(code="missing_trip_edge", severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # A batch of trips at a time through the shared reader rather than a grouping of the whole
    # table built here. Its key set and its sort are already this rule's: every trip id with a
    # row, and stop_sequence with an unset one sorting as 0.
    ids = multimap_order(stop_time_trips.trip_ids(feed))
    for trip_id, rows in stop_time_trips.stream_in_order(feed, ids):
        first, last = rows[0], rows[-1]
        for edge in (first, last):
            # Both window fields absent, as upstream tests them together.
            if any(edge.get(field) is not None for field in WINDOW_FIELDS):
                continue
            for field in EDGE_FIELDS:
                if edge.get(field) is not None:
                    continue
                yield Notice(
                    "missing_trip_edge",
                    Severity.ERROR,
                    {
                        "csvRowNumber": edge["_row_number"],
                        "stopSequence": edge.get("stop_sequence"),
                        "tripId": trip_id,
                        "specifiedField": field,
                    },
                )
