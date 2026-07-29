"""PathwayStopAccessValidator: a pathway may not reach a stop marked unreachable by one.

`stop_access` is how a feed says "this platform is not entered through the station's
pathway graph", so a pathway naming it contradicts the stop's own declaration.

Two upstream details are load-bearing:

- **A header gate.** `shouldCallValidate` tests that stops.txt *declares* stop_access, so
  a feed without the column is silent even when it would otherwise have something to say.
- **One notice per pathway per stop.** A pathway whose two endpoints are the same flagged
  stop draws a single notice, because upstream guards with a set of emitted stop ids.

The reported platformCode is the *stop's*, and an absent one renders as "" rather than
dropping the key, measured, even though the Java field is non-final and nullable.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.pathways import FROM_STOP_ID, TO_STOP_ID, index_of
from gtfs_validator.rules.registry import file_rule

CODE = "pathway_to_stop_with_access_outside_of_station_pathways"
STOP_ACCESS = "stop_access"

# GtfsStopAccess.NOT_ACCESSIBLE_VIA_PATHWAYS.
NOT_ACCESSIBLE_VIA_PATHWAYS = 1


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    if not feed.has_column("stops.txt", STOP_ACCESS):
        return
    index = index_of(feed)
    flagged = {
        stop_id: stop.get("platform_code") or ""
        for stop_id, stop in index.stops.items()
        if stop.get(STOP_ACCESS) == NOT_ACCESSIBLE_VIA_PATHWAYS
    }
    if not flagged:
        return
    for row in index.pathways:
        emitted: set[str] = set()
        for field in (FROM_STOP_ID, TO_STOP_ID):
            stop_id = row.get(field)
            # A blank endpoint is skipped before the lookup, matching upstream's
            # isBlank guard rather than relying on the id being absent from the map.
            if stop_id is None or not stop_id.strip() or stop_id not in flagged:
                continue
            if stop_id in emitted:
                continue
            emitted.add(stop_id)
            yield Notice(
                CODE,
                Severity.ERROR,
                {
                    "csvRowNumber": row["_row_number"],
                    "platformCode": flagged[stop_id],
                    "pathwayId": row.get("pathway_id") or "",
                    "stopId": stop_id,
                },
            )
