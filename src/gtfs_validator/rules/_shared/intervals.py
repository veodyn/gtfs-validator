"""ServiceInterval and its cache, ported from upstream's util package.

An interval map rather than the date set in `calendars.py`, and deliberately a
second port of the same upstream data. The two differ in two measured ways, both
of which change a reported window:

- **Exception order.** This applies `calendar_dates` rows in row order, so a date
  removed on one row and added back on a later one ends up active, while
  `ServicePeriod` unions the additions and then subtracts the removals and leaves
  it inactive either way. Measured: the window ends 2026-01-20 for
  remove-then-add and 2026-01-12 for add-then-remove.
- **Unrecognised exception types.** `ServiceIntervalCache.build` switches on the
  enum with a `default: // Unknown exception type` that ignores the row, while
  `createServicePeriod` uses a ternary that files anything not `SERVICE_ADDED`
  under removals. Measured: an `exception_type` of 7 naming the service's last
  active day leaves the window ending on that day, so the row is ignored here.

Upstream keeps both helpers for these reasons, and each validator picks one:
`ExpiredCalendarValidator` reads `CalendarUtil`, while
`FeedServiceWindowValidator` and `ServiceSpreadValidator` read this.
"""

from __future__ import annotations

import bisect
import datetime
from collections.abc import Iterable, Iterator

from gtfs_validator.rules._shared.calendars import SERVICE_ADDED, to_date, weekly_pattern

ONE_DAY = datetime.timedelta(days=1)
# GtfsCalendarDateExceptionType.SERVICE_REMOVED. Anything that is neither this nor
# SERVICE_ADDED is UNRECOGNIZED and ignored, unlike in calendars.py.
SERVICE_REMOVED = 2
# How many additions to accumulate before merging them. Additions commute, so
# flushing early is exact; this only bounds the buffer. The cap is on the total
# held across every service, not per service: one addition each for a hundred
# thousand services would otherwise keep the whole table buffered while every
# individual batch stayed under a per-service limit.
MAX_PENDING_ADDITIONS = 10_000


def _abuts_or_overlaps(first_end: datetime.date, second_start: datetime.date) -> bool:
    """Whether a run ending at first_end touches one starting at second_start.

    Expressed as a day difference rather than as `first_end + ONE_DAY >=
    second_start`, because a run ending at `date.max` is schema-valid: a
    `calendar_dates` row may name 99991231, and constructing the day after it
    raises OverflowError.
    """
    return (second_start - first_end).days <= 1


class ServiceInterval:
    """Disjoint inclusive date runs, sorted by start and merged on insert."""

    def __init__(self) -> None:
        # Parallel sorted lists rather than a dict, so a neighbour can be found by
        # bisection. Scanning every run per insert made construction quadratic in
        # the number of runs, and a Monday-only service spanning centuries has one
        # run per Monday: tens of billions of comparisons on schema-valid input.
        self._starts: list[datetime.date] = []
        self._ends: list[datetime.date] = []

    def add_interval(self, start: datetime.date, end: datetime.date, pattern: int) -> None:
        """Add every day in [start, end] whose weekday the pattern includes.

        Raises on an inverted range, *before* the zero-pattern return, because
        `addInterval` opens with a `Preconditions.checkArgument`. That is not a
        detail: measured on a feed whose calendar row runs 20261231 to 20260101,
        the jar reports two `runtime_exception_in_validator_error` entries naming
        FeedServiceWindowValidator and ServiceSpreadValidator, and **none** of
        their five notices. Silently adding nothing instead let a later
        calendar_dates addition produce a window upstream never reports.

        Note `createServicePeriod` clamps the same row rather than raising, so
        `trip_coverage_not_active_for_next7_days`, which reads that helper, still
        fires. This is the third measured difference between the two helpers.

        Then returns on a zero pattern, before touching the range: a calendar row
        with no active days contributes nothing while its `calendar_dates` rows
        still do.
        """
        if start > end:
            raise ValueError(
                f"serviceStart ({start}) must be before or equal to serviceEnd ({end})"
            )
        if pattern == 0:
            return
        run_start: datetime.date | None = None
        current = start
        while current <= end:
            if (pattern >> current.weekday()) & 1:
                if run_start is None:
                    run_start = current
                if current == end:
                    self._merge(run_start, current)
                    run_start = None
            elif run_start is not None:
                self._merge(run_start, current - ONE_DAY)
                run_start = None
            # Guard the increment rather than the loop test: a range ending at
            # date.max would otherwise raise OverflowError on the step past it.
            if current == end:
                break
            current += ONE_DAY

    def add_date(self, day: datetime.date) -> None:
        self._merge(day, day)

    def add_dates(self, days: Iterable[datetime.date]) -> None:
        """Add a batch of dates in one linear merge.

        Additions commute with each other, so a run of consecutive addition rows
        can be applied as a set. Applying them one at a time is quadratic: bisect
        finds the position in log time but the list insert shifts every element
        after it, and a descending calendar_dates file inserts at position zero
        every time. Measured before this existed: 5,000 descending additions took
        0.017s, 20,000 took 0.256s and 60,000 took 1.96s.
        """
        ordered = sorted(set(days))
        if not ordered:
            return
        # Coalesce the batch into runs first, so the merge below is between two
        # sorted disjoint sequences.
        batch: list[tuple[datetime.date, datetime.date]] = []
        for day in ordered:
            if batch and _abuts_or_overlaps(batch[-1][1], day):
                batch[-1] = (batch[-1][0], max(batch[-1][1], day))
            else:
                batch.append((day, day))

        merged: list[tuple[datetime.date, datetime.date]] = []
        existing = self.intervals()
        left = right = 0
        while left < len(existing) or right < len(batch):
            if right >= len(batch) or (
                left < len(existing) and existing[left][0] <= batch[right][0]
            ):
                run = existing[left]
                left += 1
            else:
                run = batch[right]
                right += 1
            if merged and _abuts_or_overlaps(merged[-1][1], run[0]):
                merged[-1] = (merged[-1][0], max(merged[-1][1], run[1]))
            else:
                merged.append(run)
        self._starts = [start for start, _ in merged]
        self._ends = [end for _, end in merged]

    def remove_date(self, day: datetime.date) -> None:
        """Split or trim whichever run contains the date, if any.

        `floorEntry` upstream: the run with the largest start at or before the
        date, and only if the date is within its end too.
        """
        index = bisect.bisect_right(self._starts, day) - 1
        if index < 0 or day > self._ends[index]:
            return
        start, end = self._starts[index], self._ends[index]
        del self._starts[index], self._ends[index]
        pieces = []
        if start < day:
            pieces.append((start, day - ONE_DAY))
        if day < end:
            pieces.append((day + ONE_DAY, end))
        for offset, (piece_start, piece_end) in enumerate(pieces):
            self._starts.insert(index + offset, piece_start)
            self._ends.insert(index + offset, piece_end)

    def _merge(self, start: datetime.date, end: datetime.date) -> None:
        """Insert a run, absorbing only the runs it touches or abuts.

        Abutting counts, so adding the day after a run extends it rather than
        leaving two runs with an empty gap between them. `gaps()` depends on that:
        a zero-length gap would otherwise be reported.
        """
        index = bisect.bisect_left(self._starts, start)
        # The run before the insertion point may reach forward into this one.
        if index > 0 and _abuts_or_overlaps(self._ends[index - 1], start):
            index -= 1
            start = min(start, self._starts[index])
            end = max(end, self._ends[index])
            del self._starts[index], self._ends[index]
        # Then absorb every following run this one now reaches.
        while index < len(self._starts) and _abuts_or_overlaps(end, self._starts[index]):
            end = max(end, self._ends[index])
            del self._starts[index], self._ends[index]
        self._starts.insert(index, start)
        self._ends.insert(index, end)

    def intervals(self) -> list[tuple[datetime.date, datetime.date]]:
        return list(zip(self._starts, self._ends, strict=True))

    def gaps(self) -> Iterator[tuple[datetime.date, datetime.date]]:
        """The inactive spans between runs, inclusive on both ends.

        Yielded rather than collected: a sparse service over a wide range has one
        gap per run, and its only consumer looks at them one at a time. The runs
        themselves are already retained, so materialising a second structure the
        same size buys nothing.

        A run ending at date.max can have no successor, since a later run would
        have been absorbed, so the day-after arithmetic here cannot overflow.
        """
        for index in range(len(self._starts) - 1):
            yield (self._ends[index] + ONE_DAY, self._starts[index + 1] - ONE_DAY)

    def is_empty(self) -> bool:
        return not self._starts

    def first_active_date(self) -> datetime.date:
        return self._starts[0]

    def last_active_date(self) -> datetime.date:
        return self._ends[-1]


def build_service_intervals(feed) -> dict[str, ServiceInterval]:
    """ServiceIntervalCache.build: calendar.txt first, then calendar_dates.txt.

    Memoised per feed. Upstream shares one ServiceIntervalCache between its two
    validators, and the five rules here would otherwise expand every calendar five
    times over, which this module already notes is the dominant cost.
    """
    cached = feed.cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    intervals = _build_service_intervals(feed)
    feed.cache[_CACHE_KEY] = intervals
    return intervals


_CACHE_KEY = "service_intervals"


def _build_service_intervals(feed) -> dict[str, ServiceInterval]:
    intervals: dict[str, ServiceInterval] = {}
    for row in feed.rows("calendar.txt"):
        service_id = row.get("service_id")
        if service_id is None:
            continue
        interval = intervals.setdefault(service_id, ServiceInterval())
        interval.add_interval(
            to_date(row["start_date"]), to_date(row["end_date"]), weekly_pattern(row)
        )

    # Consecutive additions for one service are accumulated and applied as a batch.
    # Order only matters between an addition and a removal, because additions
    # commute with each other, so a service's pending batch is flushed when a
    # removal for *that* service arrives and again at the end.
    #
    # Bounded, because additions also commute with each other *across* batches: a
    # file listing millions of additions for one service would otherwise hold every
    # date in memory to build what may be a single run. The batch only has to be
    # large enough that the merge is amortised, not large enough to hold the table.
    pending: dict[str, list[datetime.date]] = {}
    pending_total = 0

    def flush(service_id: str) -> int:
        """Apply and drop one service's batch, returning how many it held."""
        days = pending.pop(service_id, None)
        if not days:
            return 0
        intervals[service_id].add_dates(days)
        return len(days)

    for row in feed.rows("calendar_dates.txt"):
        service_id = row.get("service_id")
        if service_id is None:
            continue
        # computeIfAbsent runs before the switch upstream, so an ignored row still
        # registers the service with an empty interval.
        intervals.setdefault(service_id, ServiceInterval())
        exception_type = row.get("exception_type")
        # A switch with an ignoring default upstream, not a two-way branch: an
        # unrecognised type leaves the date alone rather than removing it. This is
        # where the two calendar helpers disagree, and it is measured.
        if exception_type == SERVICE_ADDED:
            pending.setdefault(service_id, []).append(to_date(row["date"]))
            pending_total += 1
            if pending_total >= MAX_PENDING_ADDITIONS:
                for buffered in list(pending):
                    flush(buffered)
                pending_total = 0
        elif exception_type == SERVICE_REMOVED:
            # Only this service's batch has to go: a removal for one service cannot
            # reorder additions for another.
            pending_total -= flush(service_id)
            intervals[service_id].remove_date(to_date(row["date"]))
    for service_id in list(pending):
        flush(service_id)
    return intervals
