"""TransferDistanceValidator: a transfer between stops more than 2 km apart.

The lower band, and an INFO rather than a warning: a 2 km transfer is unusual but legitimate in a
rural feed. Its sibling `transfer_distance_too_large` takes everything over 10 km, and upstream
tests that bound first, so the two are exclusive and a transfer of exactly 2,000 m draws neither.

The distance is `S2Earth.getDistanceMeters(S2Point, S2Point)`, the vector-angle overload rather
than the haversine, because the validator converts with `.toPoint()` first. The thresholds are in
metres and the notice reports kilometres.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.transfer_distance import (
    ABOVE_2KM_METERS,
    TOO_LARGE_METERS,
    distance_context,
    measured_transfers,
)
from gtfs_validator.rules.registry import file_rule

CODE = "transfer_distance_above_2_km"


@file_rule(code=CODE, severity=Severity.INFO)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for row, distance in measured_transfers(feed):
        # Upstream's `else if`, spelled out: this band is what the other one leaves.
        if ABOVE_2KM_METERS < distance <= TOO_LARGE_METERS:
            yield Notice(CODE, Severity.INFO, distance_context(row, distance))
