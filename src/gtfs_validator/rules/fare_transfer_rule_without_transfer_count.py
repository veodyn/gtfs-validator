"""A self transfer that does not say how many transfers it covers."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.transfer_counts import COUNT, is_self_transfer
from gtfs_validator.rules.registry import rule


@rule(
    code="fare_transfer_rule_without_transfer_count",
    severity=Severity.ERROR,
    filename="fare_transfer_rules.txt",
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if is_self_transfer(row) and row.get(COUNT) is None:
        yield Notice(
            "fare_transfer_rule_without_transfer_count",
            Severity.ERROR,
            {"csvRowNumber": row["_row_number"]},
        )
