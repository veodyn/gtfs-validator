"""TripHeadsignValidator: a headsign naming a stop the vehicle has already left.

A trip whose headsign is the name of one of its own intermediate stops tells a passenger boarding
after that stop that the vehicle is heading somewhere it has been. "Intermediate" is upstream's
word for every stop but the last, so the *first* stop counts and only the last is exempt.

Two of this validator's behaviours are bugs, and a faithful port reproduces both. Neither is a
divergence, so neither is recorded as one: they are upstream's behaviour at the
pin, and matching it is the entire product.

- **A circular trip silences every trip after it.** On finding a trip whose first and last stop
  ids are equal, upstream `return`s from the whole validator rather than continuing to the next
  trip. Measured on the `headsign1` probe: its fourth trip is circular, and its fifth, whose
  headsign names its own intermediate stop, reports nothing. Trips *before* the circular one are
  unaffected, since their notices are already in the container. A feed with one circular trip
  near the top therefore gets almost none of this check.
- **The circular test compares the two ids with `==` rather than `equals`.** That is reference
  equality in Java, so on the face of it the test would depend on the loader sharing string
  instances. It does share them: measured on `headsign2`, whose circular trip begins and ends at
  a 28-character id and still silences the trip after it. So `==` answers as `equals` would, and
  a plain Python `==` is the faithful port rather than a repair of one.

The order of the two guards is observable and is pinned by a test. A trip with no headsign is
skipped *before* the circular test, so a headsign-less circular trip does not silence the feed;
measured on `headsign3`, whose first trip is both.

Memory: `stop_times.txt` is read a batch of trips at a time rather than held, for the reason
`_shared/stop_time_trips` gives at length. What is held is one light tuple per trip carrying a
headsign, plus the stops index, both bounded by tables that are not the largest in a feed.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javatext import equals_ignore_case
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import stop_coordinates, stop_time_trips
from gtfs_validator.rules.registry import file_rule

CODE = "trip_headsign_matches_intermediate_stop"
TRIPS = "trips.txt"
HEADSIGN = "trip_headsign"
STOP_ID = "stop_id"
STOP_NAME = "stop_name"
SEQUENCE = "stop_sequence"


@file_rule(code=CODE, severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    candidates = _with_headsigns(feed)
    if not candidates:
        return
    # byStopId, first row per id. An absent stops.txt leaves this empty, which is upstream's
    # empty container: every lookup misses and the rule says nothing.
    stops = stop_coordinates.stops_by_id(feed)
    # Two independent iterators over `candidates`: zip walks it for the trip fields while the
    # stream walks it for the ids it fetches. A second list of the ids would hold the feed's trips
    # twice over for no reason.
    ids = (trip_id for _, trip_id, _ in candidates)
    for (row_number, trip_id, headsign), (_, rows) in zip(
        candidates, stop_time_trips.stream_in_order(feed, ids), strict=True
    ):
        if len(rows) < 2:
            # No intermediate stop to name. `continue`, unlike the circular test below.
            continue
        last_stop_id = rows[-1].get(STOP_ID)
        if last_stop_id == rows[0].get(STOP_ID):
            # Upstream's `return`, which abandons the rest of the feed and not just this trip.
            return
        for stop_time in rows[:-1]:
            if _names(stops, stop_time.get(STOP_ID), headsign):
                yield Notice(
                    CODE,
                    Severity.INFO,
                    _context(row_number, trip_id, headsign, stop_time, last_stop_id),
                )


def _with_headsigns(feed) -> list[tuple[int, str, str]]:
    """Every trip carrying a headsign, in file order, as (row number, trip id, headsign).

    Three fields rather than the whole row, because the notice names only these and a feed's
    trips are held in full by enough rules already. `getEntities()` is file order, which is what
    `rows` gives; no bucket model is involved in this validator's output order.

    Presence is `is not None`, and the difference from truthiness is measured rather than
    theoretical. `hasTripHeadsign()` is generated from whether the *column had a value*, not from
    whether that value is non-empty, and a cell of `" "` is trimmed to `""` while staying present.
    So there are three states, not two, and the store already distinguishes them: a missing or
    empty cell is None, a whitespace-only cell is `""`, anything else is its trimmed text.

    Measured on the `whitespace1` probe, whose first trip has a headsign of `" "` and is circular:
    the jar reports **nothing at all**, because that trip counted as having a headsign, reached the
    circular test, and returned from the whole validator. Reading `""` as absent made us skip it
    and report the trip after it. `whitespace2` measures the other direction, where a `" "`
    headsign matches a stop whose name is also `" "` and the jar emits a notice with an empty
    `tripHeadsign`.
    """
    return [
        (row["_row_number"], row["trip_id"], row[HEADSIGN])
        for row in feed.rows(TRIPS)
        if row.get(HEADSIGN) is not None and row.get("trip_id") is not None
    ]


def _names(stops: dict[str, dict], stop_id: str | None, headsign: str) -> bool:
    """Whether the stop exists, has a name, and that name is the headsign ignoring case.

    `equalsIgnoreCase` rather than casefold equality; see `javatext` for where the two part. The
    two are indistinguishable on ASCII, so the rule's own test uses `Straße` against `STRASSE`,
    which casefold calls equal and Java does not.

    `hasStopName()` is the same generated presence test as `hasTripHeadsign()`, so an empty name is
    present and can match an empty headsign. Both sides of that are measured on `whitespace2`.
    """
    stop = stops.get(stop_id) if stop_id is not None else None
    if stop is None:
        return False
    name = stop.get(STOP_NAME)
    return name is not None and equals_ignore_case(name, headsign)


def _context(
    row_number: int, trip_id: str, headsign: str, stop_time: dict, last_stop_id: str | None
) -> dict:
    """The notice's six fields in Gson's order, which is the notice class's declaration order."""
    return {
        "csvRowNumber": row_number,
        "tripId": trip_id,
        "tripHeadsign": headsign,
        "stopId1": stop_time.get(STOP_ID) or "",
        # An unset stop_sequence reads as the int type's default rather than being skipped.
        "stopSequence": stop_time.get(SEQUENCE) or 0,
        "stopId2": last_stop_id or "",
    }
