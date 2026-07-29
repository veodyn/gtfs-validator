"""StopTimeArrivalAndDepartureTimeValidator: one of the two times without the other.

A stop time gives both times or neither: giving one leaves the other to be interpolated, and a
consumer cannot tell whether the vehicle waited.

`specifiedField` names the field that **is** present, not the one that is missing. That reads
backwards and is measured: a row with only an arrival reports `arrival_time`.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.stop_time_times import ARRIVAL, DEPARTURE, stream_by_trip
from gtfs_validator.rules.registry import file_rule

CODE = "stop_time_with_only_arrival_or_departure_time"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for trip_id, entries in stream_by_trip(feed):
        for entry in entries:
            has_arrival = entry[ARRIVAL] is not None
            if has_arrival == (entry[DEPARTURE] is not None):
                continue
            yield Notice(
                CODE,
                Severity.ERROR,
                {
                    "csvRowNumber": entry["row"],
                    "tripId": trip_id,
                    "stopSequence": entry["sequence"],
                    "specifiedField": ARRIVAL if has_arrival else DEPARTURE,
                },
            )
