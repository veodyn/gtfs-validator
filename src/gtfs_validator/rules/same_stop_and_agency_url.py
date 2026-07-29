"""UrlConsistencyValidator: a stop pointing at an agency's URL.

The stop half of the same check, and it runs per stop against every agency sharing the URL. A stop
can draw this and `same_stop_and_route_url` at once: the two are independent, not exclusive.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.urls import (
    AGENCY,
    AGENCY_URL,
    STOP_URL,
    STOPS,
    by_url,
    matches,
    validator_skipped,
)
from gtfs_validator.rules.registry import file_rule

CODE = "same_stop_and_agency_url"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if validator_skipped(feed):
        return
    agencies = by_url(feed, AGENCY, AGENCY_URL)
    for stop in feed.rows(STOPS):
        url = stop.get(STOP_URL)
        if url is None:
            continue
        for agency in matches(agencies, url):
            yield Notice(
                CODE,
                Severity.WARNING,
                {
                    "stopCsvRowNumber": stop["_row_number"],
                    "stopId": stop.get("stop_id"),
                    "agencyName": agency.get("agency_name"),
                    "stopUrl": url,
                    "agencyCsvRowNumber": agency["_row_number"],
                },
            )
