"""AgencyConsistencyValidator: every agency must sit in the same timezone.

The first agency's timezone is the expected one, so the notice names a row that
disagrees with row 2 rather than with the majority. Only runs at two agencies or
more, which is upstream's gate and not merely an optimisation: a lone agency reaches
the language loop but not this one.

The values compared here are already `ZoneId.getId()`: typing normalises them, because
`+0200` and `+02:00` are one zone and comparing the feed's spelling reported a mismatch
the jar does not. Measured on a two-agency feed spelling the same offset both ways.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.agency_consistency import agencies
from gtfs_validator.rules.registry import file_rule


@file_rule(code="inconsistent_agency_timezone", severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    rows = agencies(feed)
    if len(rows) < 2:
        return
    expected = rows[0].get("agency_timezone")
    for agency in rows[1:]:
        actual = agency.get("agency_timezone")
        if actual == expected:
            continue
        yield Notice(
            "inconsistent_agency_timezone",
            Severity.ERROR,
            {
                "csvRowNumber": agency["_row_number"],
                # Unreachable in a real feed rather than a chosen rendering: a blank
                # agency_timezone is a missing required field, which makes the table
                # unindexable, and this rule then sees no rows at all.
                "expected": expected or "",
                "actual": actual or "",
            },
        )
