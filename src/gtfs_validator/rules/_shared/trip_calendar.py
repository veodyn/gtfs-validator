"""TripCalendarUtil, ported from upstream's util package.

Counts trips per active service date and derives the window in which a majority of
them run. The only place in the date cohort where a *date set* is the right shape
rather than an interval map, because a count per date is the whole point: this
reads `calendars.service_dates`, not `intervals`.
"""

from __future__ import annotations

import datetime

from gtfs_validator.rules._shared.calendars import build_service_periods

# The "max trips on a typical date" index is deliberately not the absolute
# maximum, which could be an outlier. Upstream orders the counts and picks the
# i-th of N, where i is max(RATIO * N, N - LIMIT): the ratio skips a few maxima,
# and the limit stops one infrequent route with a very long service period from
# dragging the index down into its own sparse range.
MAX_SERVICE_DATE_TRIP_COUNT_RATIO = 0.90
MAX_SERVICE_DATE_TRIP_COUNT_LIMIT = 30
# A date counts as having majority service when its trip count is at least this
# fraction of that typical maximum.
MAJORITY_TRIP_COUNT_RATIO = 0.75

# Upstream accumulates these counts in Java `int`s, which wrap on overflow where
# Python's integers grow. Reaching it takes a deliberately adversarial feed, on the
# order of 600 trips each covering 999 hours at a one-second headway, but the
# counts are then sorted and thresholded, so a wrapped negative would select
# different coverage dates. Wrapping keeps the arithmetic upstream's.
_INT32_RANGE = 1 << 32
_INT32_MAX = (1 << 31) - 1


def _as_int32(value: int) -> int:
    """Reduce to signed 32-bit, matching Java int addition."""
    wrapped = value % _INT32_RANGE
    return wrapped - _INT32_RANGE if wrapped > _INT32_MAX else wrapped


def _truncating_divide(numerator: int, denominator: int) -> int:
    """Java integer division, which truncates towards zero.

    Python's // floors, so the two differ on a negative numerator, and one arises:
    a frequency row whose end_time is at or before its start_time makes
    end - start - 1 negative. For equal endpoints Java gives 0 and Python gives -1,
    so the row would contribute zero trips instead of one and could shift the
    majority-service threshold. Nothing forbids such a row in the rules
    implemented so far, so it reaches here.
    """
    if numerator < 0:
        return -((-numerator) // denominator)
    return numerator // denominator


def _row_trip_count(row: dict) -> int:
    """One frequency row's contribution: itself, plus one per headway.

    The interval is shortened by a second before dividing, because the first trip
    is already counted, so an interval that is an exact multiple of the headway
    does not gain a spurious extra trip.
    """
    count = 1
    headway = row.get("headway_secs")
    start, end = row.get("start_time"), row.get("end_time")
    if headway and headway > 0 and start is not None and end is not None:
        count = _as_int32(count + _truncating_divide(end - start - 1, headway))
    return count


def count_trips_by_date(feed) -> dict[datetime.date, int]:
    """countTripsForEachServiceDate, keyed by date and sorted on return.

    Trips are counted per service first and then added to every one of that
    service's active dates, so a service running 50 days with 3 trips contributes
    3 to each of the 50.
    """
    # Trip presence is checked before anything else is read. A feed with no trips
    # cannot draw this notice, and both the frequency scan and the calendar
    # expansion are unbounded work: upstream tests both emptiness conditions before
    # it touches frequencies.
    if next(feed.rows("trips.txt"), None) is None:
        return {}
    # Both emptiness conditions before frequencies are touched, as upstream tests
    # them: scanning the frequency table to reach an empty result is wasted work.
    # may_have_dates answers "could any service produce a date" without expanding
    # anything, so a calendar whose every service is zero-weekday or fully removed
    # short-circuits here rather than after the scan. A non-empty period map is not
    # enough on its own: it stays truthy when every expansion is empty.
    periods = build_service_periods(feed)
    if not any(period.may_have_dates() for period in periods.values()):
        return {}

    counts_by_trip: dict[str, int] = {}
    for row in feed.rows("frequencies.txt"):
        trip_id = row.get("trip_id")
        if trip_id is not None:
            # Only the running total per trip is kept, not the rows: frequencies.txt
            # is disk-backed for the same reason trips.txt is.
            counts_by_trip[trip_id] = _as_int32(
                counts_by_trip.get(trip_id, 0) + _row_trip_count(row)
            )

    count_by_service: dict[str, int] = {}
    for trip in feed.rows("trips.txt"):
        service_id = trip.get("service_id")
        if service_id is None:
            continue
        # A trip with no frequency row counts once.
        count = counts_by_trip.get(trip.get("trip_id"), 1)
        count_by_service[service_id] = _as_int32(count_by_service.get(service_id, 0) + count)

    # Expanded one service at a time and discarded, so the live memory is the
    # per-date totals plus a single service's dates rather than every service's.
    count_by_date: dict[datetime.date, int] = {}
    for service_id, count in count_by_service.items():
        period = periods.get(service_id)
        if period is None:
            continue
        for day in period.to_dates():
            count_by_date[day] = _as_int32(count_by_date.get(day, 0) + count)
    # Returned unsorted. Ordering it here allocated a list of every item tuple and
    # a second full dictionary, and the only consumer needs the sorted *counts*
    # plus the earliest and latest qualifying date, both of which it gets in one
    # pass without an ordered copy.
    return count_by_date


def majority_service_coverage(
    count_by_date: dict[datetime.date, int],
) -> tuple[datetime.date, datetime.date] | None:
    """computeMajorityServiceCoverage: the first and last majority-service dates.

    The threshold is a fraction of the count at the chosen index of the *sorted
    counts*, and the truncation to int happens twice: once on the index and once
    on the threshold itself. Both are int casts of a double in Java, which is
    truncation towards zero, and every value here is non-negative, so int() is the
    same.
    """
    if not count_by_date:
        return None
    counts = sorted(count_by_date.values())
    index = max(
        int(len(counts) * MAX_SERVICE_DATE_TRIP_COUNT_RATIO),
        len(counts) - MAX_SERVICE_DATE_TRIP_COUNT_LIMIT,
    )
    # int(N * 0.90) never reaches N, and N - LIMIT can only be smaller, so the
    # index is always in range without a clamp.
    threshold = int(MAJORITY_TRIP_COUNT_RATIO * counts[index])
    # Upstream walks a TreeMap forwards for the first qualifying date and backwards
    # for the last. The earliest and latest qualifying dates are the same answer and
    # need neither an ordered copy of the map nor a list of the qualifying keys:
    # both bounds fall out of a single pass that keeps only two dates.
    earliest: datetime.date | None = None
    latest: datetime.date | None = None
    for day, count in count_by_date.items():
        if count < threshold:
            continue
        if earliest is None or day < earliest:
            earliest = day
        if latest is None or day > latest:
            latest = day
    if earliest is None or latest is None:
        # Upstream's firstKey/lastKey fallback. Unreachable in practice, since the
        # threshold is a fraction of a count that is itself in the map, but the
        # port keeps it.
        return (min(count_by_date), max(count_by_date))
    return (earliest, latest)
