"""TransferDistanceValidator: a transfer between stops more than 10 km apart.

The upper band, tested first upstream, so it takes every transfer over 10 km and leaves the 2 to
10 km range to `transfer_distance_above_2_km`.

An unresolvable stop lands here rather than being skipped. `StopUtil.getStopOrParentLatLng` falls
back to `S2LatLng.CENTER`, latitude 0 and longitude 0, so a transfer naming a stop that does not
exist is measured against a point in the Gulf of Guinea and is reported at thousands of
kilometres. Measured at 8568.438594310714 km from a stop in New York.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.transfer_distance import (
    TOO_LARGE_METERS,
    distance_context,
    measured_transfers,
)
from gtfs_validator.rules.registry import file_rule

CODE = "transfer_distance_too_large"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for row, distance in measured_transfers(feed):
        if distance > TOO_LARGE_METERS:
            yield Notice(CODE, Severity.WARNING, distance_context(row, distance))
