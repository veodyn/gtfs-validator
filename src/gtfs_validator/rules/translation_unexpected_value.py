"""TranslationFieldAndReferenceValidator: a translations row carrying an id it must not.

Two ways to earn it, and a row can earn it twice:

- **A `field_value` translation names a record.** The two addressing styles are exclusive:
  either you match on the old value or you point at a record. Carrying both reports each id
  present, so a row with `field_value`, `record_id` and `record_sub_id` draws two notices.
- **The parent has fewer key columns than the row has ids.** A translation of stops.txt may
  not carry `record_sub_id`, because a stop is addressed by one column; one of feed_info.txt
  may carry neither. Measured on both.

The notice names the field and its value but not the table, so two rows disagreeing about
different parents are indistinguishable in the report.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import translations
from gtfs_validator.rules.registry import file_rule

CODE = "translation_unexpected_value"


def _notice(row: dict, field: str) -> Notice:
    return Notice(
        CODE,
        Severity.ERROR,
        {
            "csvRowNumber": row["_row_number"],
            "fieldName": field,
            "fieldValue": row.get(field) or "",
        },
    )


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    rows = translations.rows_of(feed)
    if translations.first_pass_failed(rows):
        return
    for row in rows:
        # `hasFieldValue()` then `hasRecordId()`/`hasRecordSubId()`, all presence: an empty
        # field_value still takes this branch, and an empty id is still an unexpected value,
        # reported with the empty string. Measured on `tr2`.
        if row.get(translations.FIELD_VALUE) is not None:
            for field in (translations.RECORD_ID, translations.RECORD_SUB_ID):
                if row.get(field) is not None:
                    yield _notice(row, field)
            continue
        parent = translations.parent_filename(row)
        keys = translations.key_columns(parent)
        if keys is None or feed.is_missing(parent):
            # An unknown parent is its own notice, and its key columns are unknowable.
            continue
        # Short-circuiting `||`, as in missing_required_field: a wrong record_id stops the
        # row before record_sub_id is examined.
        for field, expected in translations.presence_checks(keys):
            if (row.get(field) is not None) == expected:
                continue
            if not expected:
                yield _notice(row, field)
            break
