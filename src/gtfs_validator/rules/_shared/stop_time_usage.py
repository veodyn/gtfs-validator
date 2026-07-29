"""One streaming pass over stop_times.txt, shared by the four usage rules.

Upstream reads a `GtfsStopTimeTableContainer` with `byTripId` and `byStopId` indexes, which
means the whole table in memory. That is not available here: a full index over
stop_times.txt is the largest table in a real feed, and materialising it is the cost bug the
scale harness exists to catch.

Every rule that needs the table turns out to want an *aggregate* rather than the rows, so
this walks it once and keeps only per-trip and per-stop summaries. On a well-formed feed
that is bounded by trips and stops rather than by stop times: the 24,000-trip scale feed has
96,000 stop times and this holds about 30,000 small integers, measured at +6 MB.

It is **not** bounded by the *declared* trips and stops, and saying so was wrong. The keys
are whatever trip_id and stop_id values stop_times.txt contains, so a feed naming 1,005
trip_ids that trips.txt never declares produces 1,005 entries against one declared trip; the
jar keeps those rows too and reports 1,005 foreign-key violations. The bound is the number of
*distinct* ids in stop_times.txt, which is the row count in the worst case.

File order matters twice and is preserved by the store's insertion order:

- `unsorted_stop_times` compares each row's stop_sequence with the previous row *for that
  trip*, so a container sorted by sequence would make the check unable to fire. Measured on
  a trip whose sequence goes backwards, which the jar does report.
- `location_with_unexpected_stop_time` reports `stopTimes.get(0)`, the earliest row naming
  the stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_CACHE_KEY = "stop_time_usage"


@dataclass
class TripSpan:
    """What `unsorted_stop_times` needs about one trip: how many rows, and where."""

    count: int = 0
    start: int = 0
    end: int = 0
    last_sequence: int | None = None
    out_of_order: bool = False

    @property
    def non_contiguous(self) -> bool:
        """Whether this trip's rows leave a gap between its first and its last.

        `span > count`, upstream. Any gap counts, and it need not be another trip's rows: a
        blank physical record between two of a trip's rows consumes a row number without
        producing a stop time, and the jar reports the trip with the span that blank line
        widened. Measured. A trip whose stop_sequence rises the whole way is still reported,
        which the notice's name does not suggest.
        """
        return self.end - self.start + 1 > self.count


@dataclass
class Usage:
    trips: dict[str, TripSpan] = field(default_factory=dict)
    # The earliest stop_times row naming each stop, which is the one a notice reports.
    first_row_by_stop: dict[str, int] = field(default_factory=dict)
    location_group_ids: set[str] = field(default_factory=set)


def usage_of(feed) -> Usage:
    cached = feed.cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    usage = Usage()
    for row in feed.rows("stop_times.txt"):
        row_number = row["_row_number"]
        trip_id = row.get("trip_id")
        if trip_id is not None:
            span = usage.trips.get(trip_id)
            if span is None:
                span = TripSpan(start=row_number, end=row_number)
                usage.trips[trip_id] = span
            span.count += 1
            span.start = min(span.start, row_number)
            span.end = max(span.end, row_number)
            sequence = row.get("stop_sequence")
            if sequence is not None:
                # `<=`, so a repeated stop_sequence counts as out of order too.
                if span.last_sequence is not None and sequence <= span.last_sequence:
                    span.out_of_order = True
                span.last_sequence = sequence
        stop_id = row.get("stop_id")
        if stop_id:
            usage.first_row_by_stop.setdefault(stop_id, row_number)
        group_id = row.get("location_group_id")
        if group_id:
            usage.location_group_ids.add(group_id)
    feed.cache[_CACHE_KEY] = usage
    return usage


def stops_reached_through_location_groups(feed) -> set[str]:
    """Stops a stop time reaches indirectly, by naming a location group they belong to.

    Exempts them from `stop_without_stop_time`: the stop is served, just not by name.
    """
    used_groups = usage_of(feed).location_group_ids
    if not used_groups:
        return set()
    return {
        row["stop_id"]
        for row in feed.rows("location_group_stops.txt")
        # The stop id is added unconditionally once the group is resolved, so an empty one
        # still exempts its stop. The two tests above it, on stop_times, really are
        # `isEmpty()` and stay truthiness.
        if row.get("location_group_id") in used_groups and row.get("stop_id") is not None
    }
