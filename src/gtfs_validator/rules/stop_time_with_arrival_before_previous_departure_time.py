"""StopTimeArrivalAndDepartureTimeValidator: arriving before the vehicle last left.

Times along a trip must not go backwards. The comparison is against the previous *departure*, and the
baseline advances only on a row that has one: a middle row with an arrival and no departure does not
reset it, so a later arrival is measured against the last row that actually departed. Measured on a
trip whose third row departs at 08:20 and whose fourth arrives at 08:10.

The notice names both rows, and `departureTime` is the earlier row's, which is the value the arrival
is being compared against rather than anything on the reported row.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.render import hhmmss
from gtfs_validator.rules._shared.stop_time_times import ARRIVAL, DEPARTURE, stream_by_trip
from gtfs_validator.rules.registry import file_rule

CODE = "stop_time_with_arrival_before_previous_departure_time"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for trip_id, entries in stream_by_trip(feed):
        previous = None
        for entry in entries:
            arrival = entry[ARRIVAL]
            if arrival is not None and previous is not None and arrival < previous[DEPARTURE]:
                yield Notice(
                    CODE,
                    Severity.ERROR,
                    {
                        "csvRowNumber": entry["row"],
                        "prevCsvRowNumber": previous["row"],
                        "tripId": trip_id,
                        "arrivalTime": hhmmss(arrival),
                        "departureTime": hhmmss(previous[DEPARTURE]),
                    },
                )
            if entry[DEPARTURE] is not None:
                previous = entry
