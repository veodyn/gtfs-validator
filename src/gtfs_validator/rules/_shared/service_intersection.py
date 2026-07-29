"""`ServiceIdIntersectionCache` and `CalendarUtil.firstIntersectingDate`.

The first date two services both run, which a rule reports when it finds two things scheduled
against each other. Only the *first* such date is reported, so the answer depends on the sets
being walked in order, and both are.

The cache is upstream's and is not an optimisation that can be dropped. A block of `n` trips
asks about `n * (n - 1) / 2` service pairs and almost all of them repeat, since a block usually
runs one or two services; expanding a calendar per question instead is the shape that made the
service-window cohort slow. It keys on the pair sorted, because the answer does not depend on
which way round the question came.

What it does *not* do is expand every service up front. `calendars.service_dates` builds the
whole map and says in its own docstring why a rule should not call it: the expansion of one
service is unbounded in its calendar's width, so holding all of them at once is unbounded in
the feed. This expands a service the first time it is asked about and keeps that one, which
bounds the retained set by the services a block actually names rather than by the feed.

It is worth being exact about what the merge walk below saves, because it is less than it looks.
Both services' whole date lists are already built by the time the walk starts, so the walk saves
only the *comparisons*, not the expansion: it stops at the first shared date instead of
intersecting two sets. Upstream is the same shape, building its entire `serviceDates` map before
the cache is constructed. The expansion is bounded here by which services get asked about at all,
and by nothing the walk does.
"""

from __future__ import annotations

import datetime

from gtfs_validator.rules._shared import calendars


class ServiceIntersections:
    """Answers "what is the first date these two services share?", remembering what it is told."""

    def __init__(self, feed) -> None:
        self._periods = calendars.build_service_periods(feed)
        self._dates: dict[str, list[datetime.date]] = {}
        self._answers: dict[tuple[str, str], datetime.date | None] = {}

    def first_shared_date(self, first: str, second: str) -> datetime.date | None:
        """The earliest date both services run, or None.

        None when either service has no active dates **even if the two ids are equal**, which
        is upstream's documented behaviour and not an oversight: a service that never runs
        cannot collide with itself.
        """
        key = (first, second) if first <= second else (second, first)
        if key in self._answers:
            return self._answers[key]
        answer = _first_shared(self._dates_for(key[0]), self._dates_for(key[1]))
        self._answers[key] = answer
        return answer

    def _dates_for(self, service_id: str) -> list[datetime.date]:
        cached = self._dates.get(service_id)
        if cached is None:
            period = self._periods.get(service_id)
            cached = [] if period is None else period.to_dates()
            self._dates[service_id] = cached
        return cached


def _first_shared(first: list[datetime.date], second: list[datetime.date]) -> datetime.date | None:
    """A merge walk over two ascending lists, stopping at the first date in both.

    Upstream walks two `SortedSet` iterators rather than intersecting them, and the saving is in
    the walk and not in the expansion: both lists exist before this is called. On a feed whose
    calendars span years the answer is usually a few days in, so the walk touches a handful of
    dates where building the intersection would touch every one of them.
    """
    left = right = 0
    while left < len(first) and right < len(second):
        if first[left] == second[right]:
            return first[left]
        if first[left] < second[right]:
            left += 1
        else:
            right += 1
    return None
