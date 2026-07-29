"""FareTransferRuleDurationLimitTypeValidator, second branch."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule


@rule(
    code="fare_transfer_rule_duration_limit_type_without_duration_limit",
    severity=Severity.ERROR,
    filename="fare_transfer_rules.txt",
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if row.get("duration_limit") is None and row.get("duration_limit_type") is not None:
        yield Notice(
            "fare_transfer_rule_duration_limit_type_without_duration_limit",
            Severity.ERROR,
            {"csvRowNumber": row["_row_number"]},
        )
