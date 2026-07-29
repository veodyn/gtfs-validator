"""TranslationFieldAndReferenceValidator: a translations row pointing at a record that is not there.

The last check of the chain, so a row reaches it only if it has no `field_value`, names a table
this feed carries, and carries exactly the ids that table's key columns call for. Anything else
is one of the other three codes and stops the row before this one.

`recordSubId` renders as "" for a parent with a single key column, measured: the field is a
String upstream, so the absent value is the empty default rather than a dropped key.

The lookup is `byTranslationKey`, which upstream generates per table from
`@PrimaryKey(translationRecordIdType = ...)`. The schema generator now emits those annotations
and `_shared/translations.existing_keys` reproduces all four of its shapes, so a translation of
`frequencies.start_time` spelled `08:00:00` matches the stored seconds and a `record_sub_id` of
`+1` matches `stop_sequence` 1. Before that it was string equality against the primary key,
which reported violations on both.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import translations
from gtfs_validator.rules.registry import file_rule

CODE = "translation_foreign_key_violation"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    rows = translations.rows_of(feed)
    if translations.first_pass_failed(rows):
        return
    candidates = []
    for row in translations.resolvable_rows(feed, rows):
        keys = translations.key_columns(translations.parent_filename(row)) or ()
        wants_id, wants_sub_id = translations.expected_ids(keys)
        # A row whose ids do not match what the parent expects was already reported, either
        # as an unexpected value or as a missing required field, and upstream returns there.
        #
        # Presence, not truthiness: `isMissingOrUnexpectedField` is handed `hasRecordId()`.
        # A record_id of `""` satisfies a parent that wants one, and upstream goes on to
        # look up the empty key, which is a violation unless a row is stored under it.
        has_id = row.get(translations.RECORD_ID) is not None
        has_sub_id = row.get(translations.RECORD_SUB_ID) is not None
        if has_id != wants_id or has_sub_id != wants_sub_id:
            continue
        candidates.append(row)

    found = translations.existing_keys(feed, candidates)
    for row in candidates:
        parent = translations.parent_filename(row)
        record_id = row.get(translations.RECORD_ID) or ""
        sub_id = row.get(translations.RECORD_SUB_ID) or ""
        if (parent, record_id, sub_id) in found:
            continue
        yield Notice(
            CODE,
            Severity.ERROR,
            {
                "csvRowNumber": row["_row_number"],
                "tableName": row.get(translations.TABLE_NAME) or "",
                "recordId": record_id,
                "recordSubId": sub_id,
            },
        )
