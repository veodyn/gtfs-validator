"""TransfersInSeatTransferTypeValidator: an in-seat transfer in the middle of a trip.

The vehicle continues, so the transfer can only happen where one trip ends and the next begins: the
`from` stop must be the last stop of `from_trip_id`, and the `to` stop the first of `to_trip_id`.
Naming a stop in the middle describes passengers changing vehicles without the vehicle stopping.

Both directions are checked, so one transfer can draw two notices, and the notice names both the stop
field and the trip field so it is clear which end is wrong.

Two lookups come before the comparison, and both can skip the row. The stop must exist in stops.txt,
because upstream resolves it there first, so a stop that appears in stop_times.txt and not in
stops.txt draws nothing. And the trip must actually visit it, because that is a broken reference and
belongs to the trip-reference validator.

The whole rule is skipped when stops.txt failed to load, since its validator is injected with it.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.in_seat import (
    DIRECTIONS,
    STOP_TIMES,
    STOPS,
    in_seat_transfers,
    trip_ends,
)
from gtfs_validator.rules.registry import file_rule

CODE = "transfer_with_suspicious_mid_trip_in_seat"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if feed.dependency_failed(STOPS) or feed.dependency_failed(STOP_TIMES):
        return
    known_stops = {row["stop_id"] for row in feed.rows(STOPS) if row.get("stop_id") is not None}
    ends = trip_ends(feed)
    for transfer in in_seat_transfers(feed):
        for direction in DIRECTIONS:
            stop_id = transfer.get(direction.stop_field)
            trip_id = transfer.get(direction.trip_field)
            entry = ends.get(trip_id)
            if stop_id is None or stop_id not in known_stops:
                continue
            if entry is None or stop_id not in entry[2]:
                continue
            first, last, _ = entry
            expected = last if direction.wants_last else first
            if stop_id == expected:
                continue
            yield Notice(
                CODE,
                Severity.WARNING,
                {
                    "csvRowNumber": transfer["_row_number"],
                    "stopIdFieldName": direction.stop_field,
                    "stopId": stop_id,
                    "tripIdFieldName": direction.trip_field,
                    "tripId": trip_id,
                },
            )
