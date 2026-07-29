"""PathwayEndpointTypeValidator: a pathway must reach the boarding area, not the platform.

Fires when an endpoint is a platform that has children of its own. The test is on the
*existence* of children rather than their location type, mirroring `byParentStation`,
which is why the sibling rule for the platform's own type is a separate notice.

Both endpoints are checked, so the same platform draws one notice per pathway that names
it, at whichever end.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.location_types import STOP, location_type_of
from gtfs_validator.rules._shared.pathways import FROM_STOP_ID, TO_STOP_ID, index_of
from gtfs_validator.rules.registry import file_rule

CODE = "pathway_to_platform_with_boarding_areas"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    index = index_of(feed)
    for row in index.pathways:
        for field in (FROM_STOP_ID, TO_STOP_ID):
            stop_id = row.get(field)
            stop = index.stops.get(stop_id) if stop_id is not None else None
            if stop is None or location_type_of(stop) != STOP:
                continue
            if not index.children.get(stop_id):
                continue
            yield Notice(
                CODE,
                Severity.ERROR,
                {
                    "csvRowNumber": row["_row_number"],
                    "pathwayId": row.get("pathway_id") or "",
                    "fieldName": field,
                    "stopId": stop_id,
                },
            )
