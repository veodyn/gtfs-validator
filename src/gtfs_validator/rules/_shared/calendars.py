"""ServicePeriod and CalendarUtil, ported from upstream's util package.

A service's active dates are its weekly pattern expanded across the
`calendar.txt` range, plus its `calendar_dates.txt` additions, minus its
removals. Several rules need that set and nothing else, so it is computed here
once rather than in each of them.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

# GtfsCalendarService.NOT_AVAILABLE, and the number the generated entity returns
# for an absent value, since it is the enum's first constant.
NOT_AVAILABLE = 0
# GtfsCalendarService.AVAILABLE. The weekly pattern packs Monday at bit 0 through
# Sunday at bit 6, matching ServicePeriod.weeklyPatternFromMTWTFSS, which is also
# the order datetime.date.weekday() uses.
AVAILABLE = 1
WEEKDAY_FIELDS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
# GtfsCalendarDateExceptionType.SERVICE_ADDED. Anything else is a removal.
SERVICE_ADDED = 1
# LocalDate.EPOCH, which createServicePeriod falls back to when nothing sets a
# start. A calendar_dates-only service whose every row is a removal lands here.
EPOCH = datetime.date(1970, 1, 1)


def to_date(stored: int) -> datetime.date:
    """A YYYYMMDD integer from the store as a date.

    The store holds DATE as an integer so SQL ordering is correct, so every rule
    reading a date column converts before computing with it.
    """
    year, remainder = divmod(stored, 10000)
    month, day = divmod(remainder, 100)
    return datetime.date(year, month, day)


def to_stored(value: datetime.date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def render_gtfs_date(value: datetime.date) -> str:
    """GtfsDate.toYYYYMMDD, which is how a date-typed context field serialises.

    Eight digits, no separators, and a string rather than the integer the store
    holds. LocalDate.toString is ISO with dashes and some notices carry that
    instead, so check which one each notice uses rather than assuming this one.
    """
    return f"{value.year:04d}{value.month:02d}{value.day:02d}"


def weekly_pattern(row: dict) -> int:
    """weeklyPatternFromMTWTFSS: bit i set when day i is available.

    Upstream masks each value with 1 rather than comparing it to AVAILABLE, so
    any odd value sets the bit. A value outside the enum draws
    unexpected_enum_value in stage 3 and the cell becomes null, so only 0, 1 and
    None actually reach here.
    """
    pattern = 0
    for index, name in enumerate(WEEKDAY_FIELDS):
        pattern |= (1 & (row.get(name) or 0)) << index
    return pattern


@dataclass
class ServicePeriod:
    start: datetime.date
    end: datetime.date
    pattern: int
    added_days: set[datetime.date] = field(default_factory=set)
    removed_days: set[datetime.date] = field(default_factory=set)

    def may_have_dates(self) -> bool:
        """Whether an expansion could yield anything, without doing it.

        **Conservative, not exact**, and the "may" is load-bearing. A non-zero
        pattern can still yield nothing: a Monday-only service over a Tuesday to
        Wednesday range has no active day, and removals can cancel every day the
        pattern selects. Both return true here.

        An exact answer needs the expansion, which is the unbounded work this
        exists to avoid, so a false positive costs a caller the scan it hoped to
        skip and never changes an answer. An earlier version of this docstring
        claimed exactness, which was simply wrong.
        """
        return self.pattern != 0 or bool(self.added_days - self.removed_days)

    def to_dates(self) -> list[datetime.date]:
        """Every active date, sorted.

        Walks the range a day at a time, as upstream does. A feed declaring a
        range to the year 9999 therefore costs millions of dates per service.
        That is upstream's cost too, and capping it would be a silent divergence:
        such a feed is exactly what a validator should be reporting on.
        """
        active: set[datetime.date] = set()
        current = self.start
        one_day = datetime.timedelta(days=1)
        while current <= self.end:
            # date.weekday() is 0 for Monday, the same base the pattern uses.
            if (self.pattern >> current.weekday()) & 1:
                active.add(current)
            # A schema-valid calendar can declare 99991231, which is date.max.
            # Advancing past the endpoint raises OverflowError, and a walk that
            # has reached the end has nothing left to visit anyway.
            if current == self.end:
                break
            current += one_day
        active |= self.added_days
        active -= self.removed_days
        return sorted(active)


def create_service_period(calendar: dict | None, calendar_dates: list[dict]) -> ServicePeriod:
    """CalendarUtil.createServicePeriod.

    An inverted calendar range is clamped rather than rejected: upstream sets end
    to start and leaves the complaint to a dedicated validator, so this must not
    raise on one.
    """
    start: datetime.date | None = None
    end: datetime.date | None = None
    pattern = 0
    if calendar is not None:
        start = to_date(calendar["start_date"])
        end = to_date(calendar["end_date"])
        if start > end:
            end = start
        pattern = weekly_pattern(calendar)

    added: set[datetime.date] = set()
    removed: set[datetime.date] = set()
    for row in calendar_dates:
        day = to_date(row["date"])
        is_added = row.get("exception_type") == SERVICE_ADDED
        if calendar is None and is_added:
            # A calendar_dates-only service takes its range from its own added
            # days. A removal does not widen it.
            start = day if start is None or start > day else start
            end = day if end is None or end < day else end
        (added if is_added else removed).add(day)

    start = EPOCH if start is None else start
    end = start if end is None else end
    return ServicePeriod(start, end, pattern, added, removed)


def build_service_periods(feed) -> dict[str, ServicePeriod]:
    """CalendarUtil.buildServicePeriodMap, keyed by service_id.

    Every service in calendar.txt, then every service appearing only in
    calendar_dates.txt. A service in both is built from its calendar row plus its
    exception rows.
    """
    dates_by_service: dict[str, list[dict]] = {}
    for row in feed.rows("calendar_dates.txt"):
        service_id = row.get("service_id")
        if service_id is not None:
            dates_by_service.setdefault(service_id, []).append(row)

    periods: dict[str, ServicePeriod] = {}
    for row in feed.rows("calendar.txt"):
        service_id = row.get("service_id")
        if service_id is None:
            continue
        periods[service_id] = create_service_period(row, dates_by_service.get(service_id, []))
    for service_id, rows in dates_by_service.items():
        if service_id not in periods:
            periods[service_id] = create_service_period(None, rows)
    return periods


def service_dates(feed) -> dict[str, list[datetime.date]]:
    """CalendarUtil.servicePeriodToServiceDatesMap.

    Deliberately **not** memoised, and deliberately not what the rules that need it
    call. Sharing one map between two rules means retaining every service's
    expanded date list for as long as either might read it, and that total is
    unbounded in the calendar's width: a memoised version made expired_calendar
    hold the whole thing whenever trip coverage bailed out early and never consumed
    it.

    Sharing the expansion and bounding the memory are in direct conflict here, and
    the spec settles it: bounded memory wins, so each caller iterates
    build_service_periods and expands one service at a time. This function remains
    as the faithful port of the upstream method and for tests; a rule that calls it
    is materialising the map on purpose.
    """
    return {
        service_id: period.to_dates() for service_id, period in build_service_periods(feed).items()
    }
