"""TransfersStopTypeValidator: a transfer may only name a platform or a station.

An entrance, a generic node and a boarding area are all rejected: a transfer describes a
passenger moving between places trips call at, and those three are structure around such a
place rather than one. Both ends are checked, so one transfer can draw two notices, and
`stopIdFieldName` says which end.

**Two validators emit this code**, and they disagree about stations. TransfersStopTypeValidator, the
loop below, accepts a station for any transfer. TransfersInSeatTransferTypeValidator rejects one for
an in-seat transfer, type 4 or 5, because the vehicle cannot continue through a station's own record.
So a type-4 transfer between two stations draws two notices, one per direction, where an ordinary
transfer between the same two stations draws none. Measured; having only the first half reported
nothing for that feed.

The notice carries **five** fields, not the four the notice manifest lists: it reports both
`locationTypeValue` and `locationTypeName`, measured. An end naming a stop that does not exist
is skipped, leaving the broken reference to foreign_key_violation.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.enums import enum_name
from gtfs_validator.rules._shared.in_seat import DIRECTIONS, STOP_TIMES, in_seat_transfers
from gtfs_validator.rules._shared.location_types import STATION, STOP, location_type_of
from gtfs_validator.rules.registry import file_rule

CODE = "transfer_with_invalid_stop_location_type"
FILENAME = "transfers.txt"
STOPS = "stops.txt"
# The endpoint-type half only needs the stop fields; the in-seat half needs the shared
# Direction records, which carry the trip field too.
STOP_FIELDS = ("from_stop_id", "to_stop_id")
VALID_TYPES = (STOP, STATION)


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    stops = _stops_by_id(feed)
    # In-seat first: upstream registers TransfersInSeatTransferTypeValidator ahead of
    # TransfersStopTypeValidator, and above the 1,000-sample cap the order decides which notices a
    # report keeps. Measured on a 1,200-notice mixed probe, where running the generic half first kept
    # 200 contexts the jar does not.
    yield from _in_seat_stations(feed, stops)
    yield from _endpoint_types(feed, stops)


def _in_seat_stations(feed, stops: dict[str, dict]) -> Iterator[Notice]:
    """The in-seat half: a station is never a valid end of an in-seat transfer.

    Gated on stop_times.txt because its validator is injected with it, while the endpoint half below
    is not and must keep running: with a failed stop_times.txt the jar still reports an entrance
    endpoint and no longer reports the station.
    """
    if feed.dependency_failed(STOP_TIMES):
        return
    for transfer in in_seat_transfers(feed):
        for direction in DIRECTIONS:
            stop_id = transfer.get(direction.stop_field)
            stop = stops.get(stop_id) if stop_id is not None else None
            if stop is None or location_type_of(stop) != STATION:
                continue
            yield _notice(transfer["_row_number"], direction.stop_field, stop_id, STATION)


def _stops_by_id(feed) -> dict[str, dict]:
    # setdefault, not a dict comprehension: a duplicate stop_id draws duplicate_key and
    # upstream's generated index keeps the **first** entity, so a stop defined as a platform and
    # then again as an entrance is a platform to this rule. Overwriting reported a transfer the
    # jar accepts.
    stops: dict[str, dict] = {}
    for row in feed.rows(STOPS):
        stop_id = row.get("stop_id")
        if stop_id is not None:
            stops.setdefault(stop_id, row)
    return stops


def _notice(row_number: int, field: str, stop_id: str, location_type: int) -> Notice:
    return Notice(
        CODE,
        Severity.ERROR,
        {
            "csvRowNumber": row_number,
            "stopIdFieldName": field,
            "stopId": stop_id,
            "locationTypeValue": location_type,
            "locationTypeName": enum_name(STOPS, "location_type", location_type) or "",
        },
    )


def _endpoint_types(feed, stops: dict[str, dict]) -> Iterator[Notice]:
    for row in feed.rows(FILENAME):
        for field in STOP_FIELDS:
            stop_id = row.get(field)
            stop = stops.get(stop_id) if stop_id is not None else None
            if stop is None:
                continue
            location_type = location_type_of(stop)
            if location_type in VALID_TYPES:
                continue
            yield _notice(row["_row_number"], field, stop_id, location_type)
