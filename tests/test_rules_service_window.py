"""The service-window rules, asserted against measured jar output.

Every expected value came from running the jar with `-d 2026-06-01`. Dates here
render ISO with dashes, matching the manifest's `string` type for these five
notices rather than GtfsDate's eight digits.
"""

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 6, 1), country_code="US")
WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
ALL_DAYS = 0b1111111


def fire(code, tables):
    registry.load_rules()
    return list(registry.FILE_REGISTRY[code].func(FakeFeed(tables), CTX))


def calendar(service_id, start, end, days=ALL_DAYS):
    row = {"service_id": service_id, "start_date": start, "end_date": end}
    for index, name in enumerate(WEEKDAY_NAMES):
        row[name] = (days >> index) & 1
    return row


def feed_info(start, end):
    return {"feed_start_date": start, "feed_end_date": end, "_row_number": 2}


def test_a_wholly_future_service_window_is_reported():
    notices = fire(
        "future_calendar",
        {
            "calendar.txt": [calendar("S1", 20260901, 20261031)],
            "trips.txt": [{"service_id": "S1"}],
        },
    )
    assert [n.context for n in notices] == [
        {"minServiceStartDate": "2026-09-01", "currentDate": "2026-06-01"}
    ]


def test_future_calendar_fires_without_any_feed_info():
    # It sits before the feed_info guard upstream. Measured: the jar reports it for
    # a feed carrying no feed_info.txt at all, and reports it identically when one
    # is present.
    tables = {
        "calendar.txt": [calendar("S1", 20260901, 20261031)],
        "trips.txt": [{"service_id": "S1"}],
    }
    without = fire("future_calendar", tables)
    with_info = fire(
        "future_calendar", {**tables, "feed_info.txt": [feed_info(20260901, 20261031)]}
    )
    assert [n.context for n in without] == [n.context for n in with_info]


def test_a_service_starting_today_is_not_a_future_calendar():
    assert (
        fire(
            "future_calendar",
            {
                "calendar.txt": [calendar("S1", 20260601, 20261031)],
                "trips.txt": [{"service_id": "S1"}],
            },
        )
        == []
    )


def test_a_service_outside_the_feed_period_is_reported_per_service():
    # Measured: EARLY starts 31 days before the feed period and LATE ends 31 days
    # after it, and each draws its own notice.
    notices = fire(
        "service_window_outside_feed_period",
        {
            "calendar.txt": [
                calendar("EARLY", 20260101, 20260131),
                calendar("LATE", 20261201, 20261231),
            ],
            "trips.txt": [{"service_id": "EARLY"}, {"service_id": "LATE"}],
            "feed_info.txt": [feed_info(20260201, 20261130)],
        },
    )
    by_service = {n.context["serviceId"]: n.context for n in notices}
    assert by_service["EARLY"] == {
        "serviceId": "EARLY",
        "serviceWindowStartDate": "2026-01-01",
        "serviceWindowEndDate": "2026-01-31",
        "daysBeforeFeedStart": 31,
        "daysAfterFeedEnd": 0,
    }
    assert by_service["LATE"]["daysAfterFeedEnd"] == 31
    assert by_service["LATE"]["daysBeforeFeedStart"] == 0


def test_a_service_inside_the_feed_period_is_not_reported():
    assert (
        fire(
            "service_window_outside_feed_period",
            {
                "calendar.txt": [calendar("S1", 20260601, 20260630)],
                "trips.txt": [{"service_id": "S1"}],
                "feed_info.txt": [feed_info(20260501, 20260801)],
            },
        )
        == []
    )


def test_no_feed_info_suppresses_the_service_window_notice():
    # Unlike future_calendar, this branch is after the feed_info guard.
    assert (
        fire(
            "service_window_outside_feed_period",
            {
                "calendar.txt": [calendar("S1", 20260101, 20260131)],
                "trips.txt": [{"service_id": "S1"}],
            },
        )
        == []
    )


def test_a_feed_valid_well_beyond_its_services_is_reported():
    notices = fire(
        "feed_valid_beyond_total_service_window",
        {
            "calendar.txt": [calendar("S1", 20260601, 20260630)],
            "trips.txt": [{"service_id": "S1"}],
            "feed_info.txt": [feed_info(20260501, 20260801)],
        },
    )
    assert [n.context for n in notices] == [
        {
            "feedStartDate": "2026-05-01",
            "feedEndDate": "2026-08-01",
            "serviceWindowStartDate": "2026-06-01",
            "serviceWindowEndDate": "2026-06-30",
        }
    ]


def test_exactly_fourteen_days_of_excess_is_not_reported():
    # THRESHOLD_DAYS is 14 and isBefore/isAfter are strict. Measured: 14 days of
    # excess on each end draws nothing and 15 days on one end draws the notice.
    assert (
        fire(
            "feed_valid_beyond_total_service_window",
            {
                "calendar.txt": [calendar("S1", 20260601, 20260630)],
                "trips.txt": [{"service_id": "S1"}],
                "feed_info.txt": [feed_info(20260518, 20260714)],
            },
        )
        == []
    )


def test_fifteen_days_of_excess_on_one_end_is_reported():
    notices = fire(
        "feed_valid_beyond_total_service_window",
        {
            "calendar.txt": [calendar("S1", 20260601, 20260630)],
            "trips.txt": [{"service_id": "S1"}],
            "feed_info.txt": [feed_info(20260517, 20260714)],
        },
    )
    assert notices[0].context["feedStartDate"] == "2026-05-17"


def test_only_the_first_feed_info_row_is_read():
    # Measured: a second, far wider feed_info row draws nothing, so it is ignored
    # rather than merged. future_feed in plan 4 takes the minimum across rows; this
    # reads row zero.
    tables = {
        "calendar.txt": [calendar("S1", 20260601, 20260630)],
        "trips.txt": [{"service_id": "S1"}],
        "feed_info.txt": [feed_info(20260601, 20260630), feed_info(20200101, 20991231)],
    }
    assert fire("feed_valid_beyond_total_service_window", tables) == []
    assert fire("service_window_outside_feed_period", tables) == []


def date_row(service_id, date, exception_type=1):
    return {"service_id": service_id, "date": date, "exception_type": exception_type}


def test_a_gap_of_fourteen_days_is_reported_one_day_outside_itself():
    # MAX_GAP_DAYS is 13 and lengthInDays is inclusive, so 14 is the first gap that
    # fires. The reported dates are gap.start - 1 and gap.end + 1, the last active
    # day before and the first active day after, so they bracket the gap rather
    # than bounding it. Measured: active 2026-06-01 and again 2026-06-16 gives
    # gapStartDate 2026-06-01, gapEndDate 2026-06-16, gapDurationDays 14.
    notices = fire(
        "big_gap_in_service",
        {
            "calendar.txt": [calendar("S1", 20260601, 20260601)],
            "calendar_dates.txt": [date_row("S1", 20260616)],
        },
    )
    assert [n.context for n in notices] == [
        {
            "serviceId": "S1",
            "gapStartDate": "2026-06-01",
            "gapEndDate": "2026-06-16",
            "gapDurationDays": 14,
        }
    ]


def test_a_gap_of_thirteen_days_is_not_reported():
    assert (
        fire(
            "big_gap_in_service",
            {
                "calendar.txt": [calendar("S1", 20260601, 20260601)],
                "calendar_dates.txt": [date_row("S1", 20260615)],
            },
        )
        == []
    )


def test_a_calendar_dates_only_service_has_no_gaps_reported():
    # Both ServiceSpreadValidator branches walk calendar.txt entities, not trip
    # services, so a service defined purely by calendar_dates is invisible.
    # Measured: the jar reports nothing for such a feed despite a month-long gap.
    tables = {"calendar_dates.txt": [date_row("S1", 20260601), date_row("S1", 20260701)]}
    assert fire("big_gap_in_service", tables) == []
    assert fire("service_extends_far_in_the_future", tables) == []


def test_a_service_ending_731_days_out_is_reported():
    # MAX_FUTURE_EXTENT_DAYS is 2 * 365, so days rather than calendar years.
    # Measured from 2026-06-01: 2028-05-31 is 730 days and draws nothing,
    # 2028-06-01 is 731 and draws the notice.
    assert (
        fire(
            "service_extends_far_in_the_future",
            {"calendar.txt": [calendar("S1", 20260601, 20280531)]},
        )
        == []
    )
    notices = fire(
        "service_extends_far_in_the_future",
        {"calendar.txt": [calendar("S1", 20260601, 20280601)]},
    )
    assert [n.context for n in notices] == [
        {"serviceId": "S1", "serviceWindowEndDate": "2028-06-01"}
    ]


def trip(service_id, trip_id):
    return {"service_id": service_id, "trip_id": trip_id}


def test_a_window_covering_the_coming_week_is_not_reported():
    assert (
        fire(
            "trip_coverage_not_active_for_next7_days",
            {
                "calendar.txt": [calendar("S1", 20260501, 20260901)],
                "trips.txt": [trip("S1", "T1")],
            },
        )
        == []
    )


def test_a_window_ending_before_the_horizon_is_reported_in_eight_digits():
    # The one notice in this cohort carrying GtfsDate rather than
    # LocalDate.toString, so no dashes. The manifest types its fields as object
    # where the other five rules' are string.
    notices = fire(
        "trip_coverage_not_active_for_next7_days",
        {
            "calendar.txt": [calendar("S1", 20260501, 20260605)],
            "trips.txt": [trip("S1", "T1")],
        },
    )
    assert [n.context for n in notices] == [
        {
            "currentDate": "20260601",
            "serviceWindowStartDate": "20260501",
            "serviceWindowEndDate": "20260605",
        }
    ]


def test_a_window_starting_after_today_is_reported():
    notices = fire(
        "trip_coverage_not_active_for_next7_days",
        {
            "calendar.txt": [calendar("S1", 20260701, 20260901)],
            "trips.txt": [trip("S1", "T1")],
        },
    )
    assert notices[0].context["serviceWindowStartDate"] == "20260701"


def test_the_window_is_the_majority_one_and_not_the_total_one():
    # MAIN runs 20 trips and ends before the horizon; TAIL runs one trip to the end
    # of the year. The total window therefore covers the coming week and the
    # majority window does not. Measured: the jar reports serviceWindowEndDate
    # 20260605, so it is the majority window. Using the total window would report
    # nothing at all, which is what this fixture exists to catch.
    notices = fire(
        "trip_coverage_not_active_for_next7_days",
        {
            "calendar.txt": [
                calendar("MAIN", 20260501, 20260605),
                calendar("TAIL", 20260501, 20261231),
            ],
            "trips.txt": [trip("MAIN", f"M{index}") for index in range(20)]
            + [trip("TAIL", "TAIL1")],
        },
    )
    assert [n.context["serviceWindowEndDate"] for n in notices] == ["20260605"]


def test_a_feed_with_no_trips_reports_nothing():
    assert (
        fire(
            "trip_coverage_not_active_for_next7_days",
            {"calendar.txt": [calendar("S1", 20260501, 20260605)]},
        )
        == []
    )


def test_service_windows_are_reported_in_multimap_key_order():
    # FeedServiceWindowValidator iterates tripTable.byServiceIdMap().keySet(), and the
    # generated container indexes with ArrayListMultimap.create(), so the keys come out
    # in the 32-bucket HashMap order javahash.multimap_order models, not in file order.
    # Below the export cap the report sorts samples and hides this; above it, which
    # 1,000 samples survive depends on emission order, which is how the 1091-LU corpus
    # feed caught it.
    from gtfs_validator.javahash import multimap_order

    service_ids = [f"S{i}" for i in range(1, 9)]
    notices = fire(
        "service_window_outside_feed_period",
        {
            "calendar.txt": [calendar(sid, 20260401, 20260501) for sid in service_ids],
            "trips.txt": [{"service_id": sid} for sid in service_ids],
            "feed_info.txt": [feed_info(20260415, 20260501)],
        },
    )
    assert [n.context["serviceId"] for n in notices] == multimap_order(service_ids)
