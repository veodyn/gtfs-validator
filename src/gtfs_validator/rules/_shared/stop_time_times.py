"""The per-trip walk both StopTimeArrivalAndDepartureTimeValidator codes need.

One validator, two codes, checked in the same pass over each trip's stop times in stop_sequence
order. The checklist for a shared source applies: both codes come out in the same trip order, both
share the one dependency (stop_times.txt itself), and they disagree about nothing, so the only thing
to get right is the order.

Trips come out in the order `Multimaps.asMap(byTripIdMap())` yields, and above the 1,000-sample
cap that decides which notices a report keeps. That is `multimap_order`: a generated container's
index is an `ArrayListMultimap`, whose backing map is pre-sized for 12 keys and so starts at 32
buckets rather than 16. Two corrections landed here, both found only after the fact:
`hashmap_order` first ignored treeified bins, and then it was the wrong collection entirely. A
feed with few trips and many stop times each reaches the cap while the capacity difference is
still visible.

The baseline for "previous departure" advances **only** on a row that has a departure. A middle row
with an arrival and no departure does not reset it, so a later arrival is compared against the last
row that actually departed. That is the detail this walk exists to hold in one place.

This walk is inherently about a trip's rows in order, and no summary answers it, so it was written
as one dict of every trip to four values per stop time. That is a full-table aggregate of the
largest file in a feed, and it used to be defensible on the measurement in this docstring: on the
24,000-trip, 96,000-stop-time scale feed the peak heap did not move at all, because the run's peak
was elsewhere and this allocation sat below it.

The measurement was right and the conclusion did not survive a bigger feed. Peak heap against
`stop_times.txt` row count was linear, and after the travel-speed cohort's own aggregate was
converted to streaming, this became the whole of what was left: 70 MB at 100,000 rows, 269 MB at
400,000, 674 MB at a million, against a 600 MB ceiling and a stated design case of ten million.
So it now yields a trip at a time, which the old docstring named as the fix and called impossible
without the table grouped by trip on disk. `FeedStore` grew that read while streaming the
travel-speed rules, and this is its second caller.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.javahash import multimap_order
from gtfs_validator.rules._shared import stop_time_trips

STOP_TIMES = "stop_times.txt"
TRIP_ID = "trip_id"
SEQUENCE = "stop_sequence"
ARRIVAL = "arrival_time"
DEPARTURE = "departure_time"
_CACHE_KEY = "stop_time_times.trip_ids"


def stream_by_trip(feed) -> Iterator[tuple[str, list[dict]]]:
    """Each trip and its four-field entries, in the multimap's key order.

    A batch of trips resident, not the table. Both callers walk the trips once in order and
    neither looks back, so a generator is all either needs, and the order is the part that has
    to be right.
    """
    ids = multimap_order(_trip_ids(feed))
    for trip_id, rows in stop_time_trips.stream_in_order(feed, ids):
        yield trip_id, _entries(rows)


def _trip_ids(feed) -> list[str]:
    """The trips this walk keys its map on, in order of first appearance.

    Only trips with a row carrying a `stop_sequence`, because a row without one is dropped
    below and upstream never saw it. Keying on a trip whose every row was dropped would put
    every later trip in a different bucket, which is a different notice order rather than one
    extra empty trip. Sharing `stop_time_trips.trip_ids`, whose key set is every trip id at
    all, would do exactly that.
    """
    cached = feed.cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    ids = list(feed.distinct_in_file_order(STOP_TIMES, TRIP_ID, SEQUENCE))
    feed.cache[_CACHE_KEY] = ids
    return ids


def _entries(rows: list[dict]) -> list[dict]:
    """One trip's four-field entries, sorted by (stop_sequence, row number).

    A row with no stop_sequence is dropped: the column is required, so such a row failed typing
    and upstream never sees it. The shared reader has already sorted by stop_sequence alone, and
    this sort adds the row number as the tie-break that this walk's container has and that one
    does not.
    """
    entries = [
        {
            "row": row["_row_number"],
            "sequence": row[SEQUENCE],
            ARRIVAL: row.get(ARRIVAL),
            DEPARTURE: row.get(DEPARTURE),
        }
        for row in rows
        if row.get(SEQUENCE) is not None
    ]
    entries.sort(key=lambda entry: (entry["sequence"], entry["row"]))
    return entries
