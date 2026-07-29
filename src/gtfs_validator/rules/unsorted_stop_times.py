"""StopTimesTripBlockOrderValidator: a trip's rows are scattered or out of sequence.

Two conditions, either of which is enough, and the second is the one the notice's name does
not suggest:

- **Out of sequence.** A row whose stop_sequence is at or below the previous row's for the
  same trip. The comparison is `<=`, so a repeat counts as well as a decrease.
- **Not contiguous.** The trip's rows span more lines than the trip has rows. Usually that
  means another trip's rows sit between its first and its last, but any gap will do: a blank
  physical record between two of the trip's rows widens the span the same way, measured.
  A trip whose sequence rises the whole way is still reported when its three rows are at
  lines 2, 3 and 10.

The notice names the span rather than the offending row, so a trip reports once however many
rows are misplaced.

Emitted in `HashMap` iteration order rather than the order the trips appear in the file,
because above the 1,000-sample cap the order decides *which* thousand a report keeps. With
1,005 unsorted trips the jar's samples begin T0714, T0956, T0715; file order begins T0000 and
keeps a different thousand. See `javahash`.

A failed stop_times.txt stops the validator rather than yielding an empty table.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javahash import hashmap_order
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.stop_time_usage import usage_of
from gtfs_validator.rules.registry import file_rule

CODE = "unsorted_stop_times"

# Upstream injects these containers, and a failure in any of them skips the validator.
DEPENDENCIES = ("stop_times.txt",)


@file_rule(code=CODE, severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if any(feed.dependency_failed(name) for name in DEPENDENCIES):
        return
    trips = usage_of(feed).trips
    for trip_id in hashmap_order(trips):
        span = trips[trip_id]
        if not (span.out_of_order or span.non_contiguous):
            continue
        yield Notice(
            CODE,
            Severity.INFO,
            {
                "tripId": trip_id,
                "startCsvRowNumber": span.start,
                "endCsvRowNumber": span.end,
            },
        )
