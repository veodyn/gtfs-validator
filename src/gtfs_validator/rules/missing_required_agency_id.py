"""AgencyConsistencyValidator: agency_id stops being optional at two agencies.

The same blank field is a `missing_recommended_field` in a one-agency feed and this
ERROR in a two-agency one, which is why the two rules read the same shared row list.

Only `agency_name` is carried, and it renders as "" rather than being dropped when
the name is blank too, the String default the generated entity returns.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.agency_consistency import FILENAME, agencies
from gtfs_validator.rules._shared.conditional_agency_id import rows_missing_agency_id
from gtfs_validator.rules.registry import file_rule


@file_rule(code="missing_required_agency_id", severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # RouteAgencyIdValidator and FareAttributeAgencyIdValidator: the same condition read from the
    # other side. Their notice passes null for the agency name, so Gson omits the key that an
    # agency.txt row carries. Two tables, one field, and a context one key shorter.
    for filename, row, several in rows_missing_agency_id(feed):
        if several:
            yield Notice(
                "missing_required_agency_id",
                Severity.ERROR,
                {"filename": filename, "csvRowNumber": row["_row_number"]},
            )

    rows = agencies(feed)
    if len(rows) < 2:
        return
    for agency in rows:
        # `!agency.hasAgencyId()`. An empty agency_id satisfies it, so this row is not
        # missing one. Measured on `ag2`, where none of the three whitespace ids is
        # reported.
        if agency.get("agency_id") is not None:
            continue
        yield Notice(
            "missing_required_agency_id",
            Severity.ERROR,
            {
                "filename": FILENAME,
                "csvRowNumber": agency["_row_number"],
                "agencyName": agency.get("agency_name") or "",
            },
        )
