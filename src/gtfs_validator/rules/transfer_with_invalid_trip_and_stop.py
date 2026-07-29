"""TransfersTripReferenceValidator: a transfer naming a trip that never calls at its stop.

The stop stands for more than itself when it is a station: the transfer is satisfied by the trip
calling at any child platform. Measured on a station whose platform one trip serves and another
does not, where only the second draws the notice.

A stop that is neither a platform nor a station expands to nothing, so an entrance always draws
this notice however the trip runs. Also measured.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.transfer_trips import (
    expanded_stop_ids,
    served_stop_ids,
    trip_references,
)
from gtfs_validator.rules.registry import file_rule

CODE = "transfer_with_invalid_trip_and_stop"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for row, direction, _trip in trip_references(feed):
        stop_id = row.get(direction.stop_field)
        if stop_id is None:
            continue
        expanded = expanded_stop_ids(feed, stop_id)
        if expanded is None:
            continue
        if expanded & served_stop_ids(feed, row[direction.trip_field]):
            continue
        yield Notice(
            CODE,
            Severity.ERROR,
            {
                "csvRowNumber": row["_row_number"],
                "tripFieldName": direction.trip_field,
                "tripId": row[direction.trip_field],
                "stopFieldName": direction.stop_field,
                "stopId": stop_id,
            },
        )
