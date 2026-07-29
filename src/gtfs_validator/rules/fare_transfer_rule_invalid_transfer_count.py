"""A self transfer whose transfer_count is out of range.

Valid counts are -1, meaning unlimited, or any positive number. Measured: 0 and -2
are reported and -1 and 3 are not, so the range is "below -1, or exactly zero"
rather than a simple lower bound.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.transfer_counts import COUNT, is_self_transfer
from gtfs_validator.rules.registry import rule

UNLIMITED = -1


@rule(
    code="fare_transfer_rule_invalid_transfer_count",
    severity=Severity.ERROR,
    filename="fare_transfer_rules.txt",
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    count = row.get(COUNT)
    if not is_self_transfer(row) or count is None:
        return
    if count >= UNLIMITED and count != 0:
        return
    yield Notice(
        "fare_transfer_rule_invalid_transfer_count",
        Severity.ERROR,
        {"csvRowNumber": row["_row_number"], "transferCount": count},
    )
