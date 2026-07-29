"""NetworkIdConsistencyValidator: a network named in two places at once.

Gated on routes.txt *declaring* network_id, not on any row carrying a value, so a
routes.txt with an always-blank network_id column still conflicts with a
networks.txt. One notice per conflicting file, so a feed with both draws two.

Measured: routes.txt with network_id plus both files draws two notices naming
route_networks.txt and networks.txt; with only route_networks.txt, one; with the
column and neither file, none; and with neither the column nor a conflict, none.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule

ROUTES = "routes.txt"
NETWORK_ID = "network_id"
# Checked in this order, which is the order the two notices appear in.
CONFLICTING_FILES = ("route_networks.txt", "networks.txt")


@file_rule(code="route_networks_specified_in_more_than_one_file", severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if not feed.has_column(ROUTES, NETWORK_ID):
        return
    for filename in CONFLICTING_FILES:
        if feed.is_missing(filename):
            continue
        yield Notice(
            "route_networks_specified_in_more_than_one_file",
            Severity.ERROR,
            {"fieldName": NETWORK_ID, "fileNameA": ROUTES, "fileNameB": filename},
        )
