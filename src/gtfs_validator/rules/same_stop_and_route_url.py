"""UrlConsistencyValidator: a stop and a route sharing one URL.

The third branch, and the only one comparing two optional URLs rather than one against
agency.txt's required field. Upstream runs it in the same loop as the stop-and-agency check, after
it, so a stop matching both draws both.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.urls import (
    ROUTE_URL,
    ROUTES,
    STOP_URL,
    STOPS,
    by_url,
    matches,
    validator_skipped,
)
from gtfs_validator.rules.registry import file_rule

CODE = "same_stop_and_route_url"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if validator_skipped(feed):
        return
    routes = by_url(feed, ROUTES, ROUTE_URL)
    for stop in feed.rows(STOPS):
        url = stop.get(STOP_URL)
        if url is None:
            continue
        for route in matches(routes, url):
            yield Notice(
                CODE,
                Severity.WARNING,
                {
                    "stopCsvRowNumber": stop["_row_number"],
                    "stopId": stop.get("stop_id"),
                    "stopUrl": url,
                    "routeId": route.get("route_id"),
                    "routeCsvRowNumber": route["_row_number"],
                },
            )
