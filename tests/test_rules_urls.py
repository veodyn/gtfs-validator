"""UrlConsistencyValidator: the three codes for a URL reused across two files.

Measured on `urlfeed`, which carries two agencies sharing one URL, a route matching an agency
only after case folding, a stop matching both an agency and a route, a stop matching a route
alone, blank URLs on both sides, and a pair differing only in a non-ASCII letter's case.
"""

from __future__ import annotations

import datetime

import pytest

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 25), country_code="US")

CODES = (
    "same_route_and_agency_url",
    "same_stop_and_agency_url",
    "same_stop_and_route_url",
)


def agency(row, agency_id, name, url):
    return {"_row_number": row, "agency_id": agency_id, "agency_name": name, "agency_url": url}


def route(row, route_id, url):
    return {"_row_number": row, "route_id": route_id, "route_url": url}


def stop(row, stop_id, url):
    return {"_row_number": row, "stop_id": stop_id, "stop_url": url}


AGENCIES = [
    agency(2, "A1", "First Agency", "https://shared.example.com/"),
    agency(3, "A2", "Second Agency", "https://shared.example.com/"),
    agency(4, "A3", "Third Agency", "https://third.example.com/"),
    agency(5, "A4", "Case Agency", "https://Ä.example.com/"),
]
ROUTES = [
    route(2, "R1", "https://shared.example.com/"),
    route(3, "R2", "HTTPS://THIRD.EXAMPLE.COM/"),
    route(4, "R3", "https://route3.example.com/"),
    route(5, "R4", None),
]
STOPS = [
    stop(2, "S1", "https://shared.example.com/"),
    stop(3, "S2", "https://route3.example.com/"),
    stop(4, "S3", None),
    stop(5, "S4", "https://ä.example.com/"),
]
TABLES = {"agency.txt": AGENCIES, "routes.txt": ROUTES, "stops.txt": STOPS}


def fire(code, tables=None, unindexable=frozenset()):
    registry.load_rules()
    feed = FakeFeed(TABLES if tables is None else tables, unindexable=unindexable)
    return [notice.context for notice in registry.FILE_REGISTRY[code].func(feed, CTX)]


def test_a_route_url_matching_an_agency_url_reports_every_agency():
    """Measured: R1 matches two agencies sharing one URL and draws two notices, in agency file
    order. Upstream looks the URL up in an ArrayListMultimap, so every entry under the key is
    reported rather than just the first."""
    assert fire("same_route_and_agency_url") == [
        {
            "routeCsvRowNumber": 2,
            "routeId": "R1",
            "agencyName": "First Agency",
            "routeUrl": "https://shared.example.com/",
            "agencyCsvRowNumber": 2,
        },
        {
            "routeCsvRowNumber": 2,
            "routeId": "R1",
            "agencyName": "Second Agency",
            "routeUrl": "https://shared.example.com/",
            "agencyCsvRowNumber": 3,
        },
        {
            "routeCsvRowNumber": 3,
            "routeId": "R2",
            "agencyName": "Third Agency",
            "routeUrl": "HTTPS://THIRD.EXAMPLE.COM/",
            "agencyCsvRowNumber": 4,
        },
    ]


def test_the_match_folds_case_and_the_notice_keeps_the_original():
    """R2's URL is upper case and A3's is lower, and they still match. The notice reports
    `HTTPS://THIRD.EXAMPLE.COM/`: only the lookup key is folded, never the reported value."""
    reported = fire("same_route_and_agency_url")
    assert reported[-1]["routeUrl"] == "HTTPS://THIRD.EXAMPLE.COM/"


def test_case_folding_is_ascii_only():
    """Measured: S4's `https://ä.example.com/` and A4's `https://Ä.example.com/` draw nothing.

    Upstream folds with `Ascii.toLowerCase`, which maps A-Z and leaves every other code point
    alone. Python's `str.lower` would fold `Ä` too and report a notice the jar does not, which
    is the whole reason `javatext.ascii_to_lower` exists.
    """
    assert [row["stopId"] for row in fire("same_stop_and_agency_url")] == ["S1", "S1"]
    assert "S4" not in {row["stopId"] for row in fire("same_stop_and_route_url")}


def test_a_stop_url_can_match_an_agency_and_a_route_at_once():
    """S1 shares its URL with two agencies and with R1, so it draws two notices under one code
    and one under the other. The two codes are independent rather than exclusive."""
    assert [row["agencyCsvRowNumber"] for row in fire("same_stop_and_agency_url")] == [2, 3]
    assert fire("same_stop_and_route_url") == [
        {
            "stopCsvRowNumber": 2,
            "stopId": "S1",
            "stopUrl": "https://shared.example.com/",
            "routeId": "R1",
            "routeCsvRowNumber": 2,
        },
        {
            "stopCsvRowNumber": 3,
            "stopId": "S2",
            "stopUrl": "https://route3.example.com/",
            "routeId": "R3",
            "routeCsvRowNumber": 4,
        },
    ]


@pytest.mark.parametrize("code", CODES)
def test_a_blank_url_on_either_side_matches_nothing(code):
    """`hasRouteUrl` and friends gate each loop, so a row with no URL is skipped rather than
    matched against other blank rows. S3 and R4 have none, and A5 here has none either."""
    tables = {
        "agency.txt": [agency(2, "A1", "No Url Agency", None)],
        "routes.txt": [route(2, "R1", None)],
        "stops.txt": [stop(2, "S1", None)],
    }
    assert fire(code, tables) == []


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("failed", ["agency.txt", "routes.txt", "stops.txt"])
def test_any_failed_table_silences_all_three_codes(code, failed):
    """Measured on a feed whose routes.txt has a short row: all three codes vanish, including
    `same_stop_and_agency_url`, which never reads routes.txt.

    One validator is injected with all three containers, and upstream skips it when any of them
    has a non-parsable status. Gating each code on only the tables it reads would report two
    codes the jar does not.

    Asserted as an outcome rather than as `pytest.raises(DependencyFailed)`, because the rules
    check `dependency_failed` explicitly instead of letting a read raise. Both reproduce
    upstream, and the outcome is what the report shows either way.
    """
    assert fire(code, unindexable=frozenset({failed})) == []


@pytest.mark.parametrize("code", CODES)
def test_distinct_urls_draw_nothing(code):
    """The negative fixture: three files, three different URLs."""
    tables = {
        "agency.txt": [agency(2, "A1", "Agency", "https://a.example.com/")],
        "routes.txt": [route(2, "R1", "https://r.example.com/")],
        "stops.txt": [stop(2, "S1", "https://s.example.com/")],
    }
    assert fire(code, tables) == []
