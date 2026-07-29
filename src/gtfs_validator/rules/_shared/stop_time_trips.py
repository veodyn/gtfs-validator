"""`byTripIdMap()` without holding it: one trip's stop times at a time.

Four rules walk `stop_times.txt` per trip in full: the two travel-speed codes,
`decreasing_or_equal_stop_time_distance` and `missing_trip_edge`. Each needs whole rows, since
between them they read stop ids, times, distances, sequences and row numbers.

The obvious shape is a dict of every trip to its rows, and that is what this was first. It is
also a full-table materialisation of the largest file in a feed, whose cost was measured as
linear at about 1.4 KB a stop time: 140 MB at 100,000 rows, 550 MB at 400,000, 1,375 MB at a
million. A ten-million-row `stop_times.txt` is this project's stated design case, so the shape
was wrong however well it read. Streaming it, together with the same change to
`stop_time_times` and `missing_trip_edge`, took the same three feeds to about 20 MB each:
**flat**, and the row count is no longer in the answer at all.

Two things do remain, and both are per *trip* rather than per row:

- The batch, bounded by `BATCH_TRIPS` trips and nothing else.
- The trip ids, at about 5 KB a trip once the ranks, the trips.txt rows and the fingerprint
  groups are counted: 262 MB for a feed of 50,000 trips, whatever its row count. The order
  upstream reports these notices in is a `HashMap` or a Guava multimap keyed by trip id, so
  the models in `gtfs_validator.javahash` need every key at once, and there is no version of this
  that streams the keys too. That floor is upstream's shape rather than a choice here.

Three ways to read the rows, and which one a caller wants depends on whether it needs the trips
in upstream's order:

- `stream_in_order` walks every trip in a given order, a batch of trips at a time. For the
  rules whose notice order is the trip-id multimap's, which is most of them.
- `rows_for_trip` seeks one trip, for a caller that wants a few rather than all of them.
- `stream_trips` takes them in whatever order is cheapest, for a caller that will reorder what
  it collects afterwards. One table scan instead of any seeking at all.

The batch in `stream_in_order` is why it exists rather than a loop over `rows_for_trip`, and it
buys less than it first appeared to. Swept over a 400,000-row feed in both shapes, against a
query per trip: 5% faster on long trips and 7% on short ones, and slightly *lower* peak heap,
because a batch of rows read together costs less than the same rows read one query at a time.
An early reading of "about twice as fast" was the machine's load average and not the change.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

STOP_TIMES = "stop_times.txt"
TRIP_ID = "trip_id"
SEQUENCE = "stop_sequence"
# Trips held at once by `stream_in_order`, chosen by sweeping 1, 16, 64 and 256 over a
# 400,000-row feed of 400-stop trips and one of 20-stop trips. 64 was the best of the four on
# both axes at once; 16 tied it on memory and was a shade slower. 256 is the interesting one,
# and the reason this is a measured number rather than a round one: it was *slower* than a query
# per trip (193s against 145s) and used three times the memory of 64 (71 MB against 20 MB),
# because a batch of 256 long trips is 100,000 rows resident and the saving on round trips had
# stopped paying long before that. A bigger buffer is not a faster one.
BATCH_TRIPS = 64
_CACHE_KEY = "stop_time_trips.trip_ids"


def trip_ids(feed) -> list[str]:
    """Every trip id in `stop_times.txt`, in order of first appearance.

    Insertion order for the bucket models, which is what `multimap_order` documents that it
    needs. A row with no `trip_id` is dropped: the column is required, so such a row failed
    typing and upstream's container never held it.
    """
    cached = feed.cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    ids = list(feed.distinct_in_file_order(STOP_TIMES, TRIP_ID))
    feed.cache[_CACHE_KEY] = ids
    return ids


def rows_for_trip(feed, trip_id: str) -> list[dict]:
    """One trip's whole stop time rows, in `stop_sequence` order."""
    return _sorted(list(feed.rows_where(STOP_TIMES, TRIP_ID, trip_id)))


def stream_in_order(feed, ordered_ids: Iterable[str]) -> Iterator[tuple[str, list[dict]]]:
    """Each of `ordered_ids` and its rows, in that order, `BATCH_TRIPS` trips resident.

    A trip with no rows still comes back, with an empty list. That cannot happen when the ids
    came from `trip_ids`, since those are the trips that have rows, and a caller passing its
    own list is better told than quietly skipped.
    """
    batch: list[str] = []
    for trip_id in ordered_ids:
        batch.append(trip_id)
        if len(batch) == BATCH_TRIPS:
            yield from _fetch(feed, batch)
            batch = []
    if batch:
        yield from _fetch(feed, batch)


def _fetch(feed, batch: list[str]) -> Iterator[tuple[str, list[dict]]]:
    fetched = feed.rows_for_keys(STOP_TIMES, TRIP_ID, batch)
    for trip_id in batch:
        yield trip_id, _sorted(fetched.get(trip_id, []))


def stream_trips(feed) -> Iterator[tuple[str, list[dict]]]:
    """Every trip and its rows, one trip resident at a time, in no order worth relying on.

    The order is the store's cheapest, which is by trip id. A caller whose output order matters
    has to sort what it collects by the rank `trip_ids` gives, and both of this helper's
    callers do exactly that.
    """
    for trip_id, rows in feed.rows_grouped_by(STOP_TIMES, TRIP_ID):
        yield trip_id, _sorted(rows)


def _sorted(rows: list[dict]) -> list[dict]:
    """By `stop_sequence`, where an unset one sorts as 0.

    The sort is here rather than in SQL because of that default: the container is indexed by
    (trip_id, stop_sequence) and the getter for an absent sequence returns the type's zero,
    which is not where SQLite puts a NULL.
    """
    rows.sort(key=lambda row: row.get(SEQUENCE) or 0)
    return rows
