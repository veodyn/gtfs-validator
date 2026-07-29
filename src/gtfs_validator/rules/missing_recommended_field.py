"""The rule-layer half of `missing_recommended_field`: four validators, one code.

The engine emits this code from stage 3 for any field the schema marks @Recommended.
Neither field here is annotated, so for these two the rule layer is the only source
and a diff showing the notice missing points at this module rather than the schema
generator.

- **FareMediaNameValidator**: a card or app fare medium needs a name. Only two of the
  five types want one; measured on a fare_media.txt whose blank-name rows are type 2,
  the jar reports both.
- **AgencyConsistencyValidator**: a lone agency should still declare agency_id. The
  same blank field becomes `missing_required_agency_id` as soon as a second agency
  exists, which is why both read the shared row list.

This is a file rule rather than two entity rules because one notice code gets one
registry entry, and the two halves need different table gates: the fare-media half
reads `entity_rows` because upstream validates it per row during loading, the agency
half reads the gated `rows` because AgencyConsistencyValidator runs after loading. The
cost is coarser failure isolation than upstream's per-entity `safeValidate` gives the
fare-media half: a raise here loses both branches for the feed rather than one row.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.agency_consistency import FILENAME as AGENCY_FILE
from gtfs_validator.rules._shared.agency_consistency import agencies
from gtfs_validator.rules._shared.conditional_agency_id import AGENCY_ID, rows_missing_agency_id
from gtfs_validator.rules.registry import file_rule

CODE = "missing_recommended_field"
FARE_MEDIA_FILE = "fare_media.txt"

# GtfsFareMediaType. NONE, PAPER_TICKET and CONTACTLESS_EMV fall through to false
# upstream, along with UNRECOGNIZED via the switch's default.
TRANSIT_CARD = 2
MOBILE_APP = 4
NAMED_TYPES = (TRANSIT_CARD, MOBILE_APP)


def _notice(filename: str, row_number: int, field_name: str) -> Notice:
    return Notice(
        CODE,
        Severity.WARNING,
        {"filename": filename, "csvRowNumber": row_number, "fieldName": field_name},
    )


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    # entity_rows, not rows: FareMediaNameValidator is a SingleEntityValidator and
    # runs on a clean row even when a later row makes the table unindexable.
    for row in feed.entity_rows(FARE_MEDIA_FILE):
        # `!entity.hasFareMediaName()`, so an empty name counts as named.
        if row.get("fare_media_type") in NAMED_TYPES and row.get("fare_media_name") is None:
            yield _notice(FARE_MEDIA_FILE, row["_row_number"], "fare_media_name")

    rows = agencies(feed)
    # `!agency.hasAgencyId()` again, the recommended half of the same condition.
    if len(rows) == 1 and rows[0].get("agency_id") is None:
        yield _notice(AGENCY_FILE, rows[0]["_row_number"], "agency_id")

    # RouteAgencyIdValidator and FareAttributeAgencyIdValidator, the third and fourth emitters
    # of this code. With one agency an absent agency_id is a recommendation; with several it is
    # missing_required_agency_id instead, which is the other rule's half of the same condition.
    for filename, row, several in rows_missing_agency_id(feed):
        if not several:
            yield _notice(filename, row["_row_number"], AGENCY_ID)
