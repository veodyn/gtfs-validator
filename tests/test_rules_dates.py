"""The date-dependent rules, asserted against measured jar output.

Every expected value came from running the jar with `-d 2026-06-01`, so these
tests do not change meaning as time passes.
"""

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

# The date every fixture is measured against.
CTX = Context(date=datetime.date(2026, 6, 1), country_code="US")
WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def fire(code, row):
    registry.load_rules()
    return list(registry.REGISTRY[code].func(row, CTX))


def fire_file(code, tables):
    registry.load_rules()
    return list(registry.FILE_REGISTRY[code].func(FakeFeed(tables), CTX))


def test_a_start_date_without_an_end_date_names_the_end_field():
    notices = fire(
        "missing_feed_info_date",
        {"feed_start_date": 20260101, "feed_end_date": None, "_row_number": 2},
    )
    assert [n.context for n in notices] == [{"csvRowNumber": 2, "fieldName": "feed_end_date"}]


def test_an_end_date_without_a_start_date_names_the_start_field():
    notices = fire(
        "missing_feed_info_date",
        {"feed_start_date": None, "feed_end_date": 20261231, "_row_number": 2},
    )
    assert [n.context for n in notices] == [{"csvRowNumber": 2, "fieldName": "feed_start_date"}]


def test_neither_or_both_dates_draw_nothing():
    for start, end in ((None, None), (20260101, 20261231)):
        assert (
            fire(
                "missing_feed_info_date",
                {"feed_start_date": start, "feed_end_date": end, "_row_number": 2},
            )
            == []
        ), (start, end)


def test_an_end_date_inside_seven_days_draws_the_seven_day_notice():
    notices = fire("feed_expiration_date7_days", {"feed_end_date": 20260604, "_row_number": 2})
    assert [n.context for n in notices] == [
        {
            "csvRowNumber": 2,
            "currentDate": "20260601",
            "feedEndDate": "20260604",
            "suggestedExpirationDate": "20260608",
        }
    ]
    assert fire("feed_expiration_date30_days", {"feed_end_date": 20260604, "_row_number": 2}) == []


def test_an_end_date_inside_thirty_days_draws_only_the_thirty_day_notice():
    assert fire("feed_expiration_date7_days", {"feed_end_date": 20260621, "_row_number": 2}) == []
    notices = fire("feed_expiration_date30_days", {"feed_end_date": 20260621, "_row_number": 2})
    assert [n.context for n in notices] == [
        {
            "csvRowNumber": 2,
            "currentDate": "20260601",
            "feedEndDate": "20260621",
            "suggestedExpirationDate": "20260701",
        }
    ]


def test_an_end_date_exactly_on_the_seven_day_suggestion_is_a_thirty_day_notice():
    # The comparison is strictly less than. Measured: an end date of 2026-06-08,
    # exactly the 7-day suggestion, draws the 30-day notice.
    assert fire("feed_expiration_date7_days", {"feed_end_date": 20260608, "_row_number": 2}) == []
    notices = fire("feed_expiration_date30_days", {"feed_end_date": 20260608, "_row_number": 2})
    assert notices[0].context["suggestedExpirationDate"] == "20260701"


def test_an_end_date_exactly_on_the_thirty_day_suggestion_draws_neither():
    for code in ("feed_expiration_date7_days", "feed_expiration_date30_days"):
        assert fire(code, {"feed_end_date": 20260701, "_row_number": 2}) == [], code


def test_a_far_future_end_date_draws_neither():
    for code in ("feed_expiration_date7_days", "feed_expiration_date30_days"):
        assert fire(code, {"feed_end_date": 20270101, "_row_number": 2}) == [], code


def test_no_end_date_draws_neither():
    for code in ("feed_expiration_date7_days", "feed_expiration_date30_days"):
        assert fire(code, {"feed_end_date": None, "_row_number": 2}) == [], code


def test_the_earliest_future_start_date_is_reported():
    # FeedValidTodayValidator takes the minimum feed_start_date across rows, not
    # the first. Measured on a feed whose rows start 2026-09-01 and 2026-07-01.
    notices = fire_file(
        "future_feed",
        {
            "feed_info.txt": [
                {"feed_start_date": 20260901, "_row_number": 2},
                {"feed_start_date": 20260701, "_row_number": 3},
            ]
        },
    )
    assert [n.context for n in notices] == [
        {"feedStartDate": "20260701", "currentDate": "20260601"}
    ]


def test_a_past_start_date_draws_no_future_feed():
    assert (
        fire_file(
            "future_feed", {"feed_info.txt": [{"feed_start_date": 20260101, "_row_number": 2}]}
        )
        == []
    )


def test_a_start_date_equal_to_today_draws_no_future_feed():
    # The comparison is strictly after, so today itself is not a future feed.
    assert (
        fire_file(
            "future_feed", {"feed_info.txt": [{"feed_start_date": 20260601, "_row_number": 2}]}
        )
        == []
    )


def test_a_missing_feed_info_draws_no_future_feed():
    assert fire_file("future_feed", {}) == []


def calendar_row(service_id, row_number, days, start=20260101, end=20261231):
    row = {
        "service_id": service_id,
        "_row_number": row_number,
        "start_date": start,
        "end_date": end,
    }
    for index, name in enumerate(WEEKDAY_NAMES):
        row[name] = (days >> index) & 1
    return row


def test_a_service_with_every_day_off_is_reported():
    notices = fire_file(
        "service_has_no_active_day_of_the_week",
        {"calendar.txt": [calendar_row("WEEK", 2, 0)]},
    )
    assert [n.context for n in notices] == [{"csvRowNumber": 2, "serviceId": "WEEK"}]


def test_a_service_with_one_day_on_is_not_reported():
    for index in range(7):
        assert (
            fire_file(
                "service_has_no_active_day_of_the_week",
                {"calendar.txt": [calendar_row("WEEK", 2, 1 << index)]},
            )
            == []
        ), WEEKDAY_NAMES[index]


def test_both_calendar_files_absent_is_reported_once_with_no_context():
    notices = fire_file("missing_calendar_and_calendar_date_files", {})
    assert [n.context for n in notices] == [{}]


def test_a_present_but_empty_calendar_is_not_a_missing_file():
    # isMissingFile is not isEmpty. Measured: a feed whose calendar.txt is
    # header-only draws nothing. This is the reason FeedView has is_missing.
    assert fire_file("missing_calendar_and_calendar_date_files", {"calendar.txt": []}) == []


def test_either_calendar_file_present_suppresses_it():
    for filename in ("calendar.txt", "calendar_dates.txt"):
        assert fire_file("missing_calendar_and_calendar_date_files", {filename: []}) == [], filename


def date_row(service_id, row_number, date, exception_type=1):
    return {
        "service_id": service_id,
        "_row_number": row_number,
        "date": date,
        "exception_type": exception_type,
    }


def test_an_expired_calendar_service_reports_its_own_row():
    notices = fire_file(
        "expired_calendar",
        {"calendar.txt": [calendar_row("S1", 2, 0b1111111, 20250101, 20250201)]},
    )
    assert [n.context for n in notices] == [{"csvRowNumber": 2, "serviceId": "S1"}]


def test_a_live_calendar_service_is_not_reported():
    assert (
        fire_file(
            "expired_calendar",
            {"calendar.txt": [calendar_row("S1", 2, 0b1111111, 20260101, 20261231)]},
        )
        == []
    )


def test_only_the_expired_service_is_reported():
    notices = fire_file(
        "expired_calendar",
        {
            "calendar.txt": [
                calendar_row("OLD", 2, 0b1111111, 20250101, 20250201),
                calendar_row("NEW", 3, 0b1111111, 20260101, 20261231),
            ]
        },
    )
    assert [n.context["serviceId"] for n in notices] == ["OLD"]


def test_calendar_dates_only_services_report_their_lowest_row():
    # calendar.txt has no entities and every service is expired, so the
    # calendar_dates branch applies and each service reports its first row.
    # Measured: A at row 2 and B at row 4.
    notices = fire_file(
        "expired_calendar",
        {
            "calendar_dates.txt": [
                date_row("A", 2, 20250110),
                date_row("A", 3, 20250101),
                date_row("B", 4, 20250201),
            ]
        },
    )
    assert [(n.context["csvRowNumber"], n.context["serviceId"]) for n in notices] == [
        (2, "A"),
        (4, "B"),
    ]


def test_one_live_calendar_dates_service_suppresses_all_of_them():
    # The post-loop guard is isCalendarTableEmpty && allCalendarAreExpired, so a
    # single unexpired service suppresses the notices for the expired ones too.
    # This is the case that separates a correct port from a plausible one, and
    # the jar reports nothing for it.
    assert (
        fire_file(
            "expired_calendar",
            {
                "calendar_dates.txt": [
                    date_row("OLD", 2, 20250101),
                    date_row("NEW", 3, 20261201),
                ]
            },
        )
        == []
    )


def test_a_non_empty_calendar_switches_off_the_calendar_dates_branch():
    # calendar.txt carries a live service, so isCalendarTableEmpty is false and an
    # expired calendar_dates-only service is not reported.
    assert (
        fire_file(
            "expired_calendar",
            {
                "calendar.txt": [calendar_row("LIVE", 2, 0b1111111, 20260101, 20261231)],
                "calendar_dates.txt": [date_row("GONE", 2, 20250101)],
            },
        )
        == []
    )


def test_a_service_with_no_active_dates_is_skipped():
    # An added day that is also removed leaves the expansion empty, and an empty
    # expansion is skipped before the expiry test rather than counting as expired.
    assert (
        fire_file(
            "expired_calendar",
            {
                "calendar_dates.txt": [
                    date_row("S", 2, 20250101, 1),
                    date_row("S", 3, 20250101, 2),
                ]
            },
        )
        == []
    )


def test_notices_are_sorted_by_row_number():
    notices = fire_file(
        "expired_calendar",
        {
            "calendar.txt": [
                calendar_row("LATER", 9, 0b1111111, 20250101, 20250201),
                calendar_row("EARLIER", 3, 0b1111111, 20250101, 20250201),
            ]
        },
    )
    assert [n.context["csvRowNumber"] for n in notices] == [3, 9]


def test_the_expiration_threshold_survives_the_maximum_validation_date():
    # Java's LocalDate spans year 999999999, so plusDays(30) from 9999-12-02 is an
    # ordinary date there and an OverflowError here. Measured: the jar validates
    # such a feed without complaint, where we recorded a validator runtime error
    # and exited nonzero.
    late = Context(date=datetime.date(9999, 12, 2), country_code="US")
    registry.load_rules()
    row = {"feed_end_date": 20261231, "_row_number": 2}
    assert len(list(registry.REGISTRY["feed_expiration_date7_days"].func(row, late))) == 1
    assert list(registry.REGISTRY["feed_expiration_date30_days"].func(row, late)) == []


def test_a_threshold_past_year_9999_still_fires_and_renders():
    # Suppressing the notice when the threshold overflows was wrong: Java computes
    # 10000-01-01 and reports it. Measured at --date 9999-12-02 with a
    # feed_end_date of 99991231, the jar reports feed_expiration_date30_days with
    # suggestedExpirationDate "100000101", nine characters, so the year field
    # widens rather than wrapping.
    late = Context(date=datetime.date(9999, 12, 2), country_code="US")
    registry.load_rules()
    row = {"feed_end_date": 99991231, "_row_number": 2}
    notices = list(registry.REGISTRY["feed_expiration_date30_days"].func(row, late))
    assert [n.context for n in notices] == [
        {
            "csvRowNumber": 2,
            "currentDate": "99991202",
            "feedEndDate": "99991231",
            "suggestedExpirationDate": "100000101",
        }
    ]
    # Inside seven days is 9999-12-09, which 99991231 is after, so the 7-day
    # branch does not claim it.
    assert list(registry.REGISTRY["feed_expiration_date7_days"].func(row, late)) == []


def test_an_out_of_enum_weekday_is_not_an_inactive_day():
    # Every day must be exactly NOT_AVAILABLE. An out-of-enum value folds to
    # UNRECOGNIZED, which is neither AVAILABLE nor NOT_AVAILABLE, so the notice
    # does not fire. Measured: the jar reports nothing for a row whose monday is 2,
    # and reports expired_calendar for it instead because UNRECOGNIZED is -1 and
    # weeklyPatternFromMTWTFSS masks with 1, setting the Monday bit.
    row = calendar_row("WEEK", 2, 0)
    row["monday"] = -1
    assert fire_file("service_has_no_active_day_of_the_week", {"calendar.txt": [row]}) == []


def test_a_duplicate_service_id_reports_its_first_row():
    # Both rows are stored, and upstream reads the row number through byServiceId,
    # whose index keeps the first entity. Measured: the jar reports csvRowNumber 2.
    notices = fire_file(
        "expired_calendar",
        {
            "calendar.txt": [
                calendar_row("WEEK", 2, 0b1111111, 20250101, 20250201),
                calendar_row("WEEK", 3, 0b1111111, 20250105, 20250210),
            ]
        },
    )
    assert [n.context["csvRowNumber"] for n in notices] == [2]
