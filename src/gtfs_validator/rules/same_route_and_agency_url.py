"""UrlConsistencyValidator: a route pointing at its agency's own URL.

A route_url should describe the route, so finding the agency's URL there means one of the two is
wrong. Every agency sharing the URL draws its own notice, in agency file order: upstream looks the
URL up in an `ArrayListMultimap` and reports each entry.

The comparison folds ASCII case only and the notice reports the URL as written. Measured: a route
whose URL is `HTTPS://THIRD.EXAMPLE.COM/` matches an agency's `https://third.example.com/` and
reports its own upper-case form.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.urls import (
    AGENCY,
    AGENCY_URL,
    ROUTE_URL,
    ROUTES,
    by_url,
    matches,
    validator_skipped,
)
from gtfs_validator.rules.registry import file_rule

CODE = "same_route_and_agency_url"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if validator_skipped(feed):
        return
    agencies = by_url(feed, AGENCY, AGENCY_URL)
    for route in feed.rows(ROUTES):
        url = route.get(ROUTE_URL)
        if url is None:
            continue
        for agency in matches(agencies, url):
            yield Notice(
                CODE,
                Severity.WARNING,
                {
                    "routeCsvRowNumber": route["_row_number"],
                    "routeId": route.get("route_id"),
                    "agencyName": agency.get("agency_name"),
                    "routeUrl": url,
                    "agencyCsvRowNumber": agency["_row_number"],
                },
            )
