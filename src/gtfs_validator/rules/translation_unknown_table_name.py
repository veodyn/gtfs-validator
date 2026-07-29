"""TranslationFieldAndReferenceValidator: a translations row naming a table that is not here.

Two different situations produce it and the notice does not distinguish them: a `table_name`
that is not a GTFS table at all, and one that is but which this feed does not carry. Measured
both ways, with `nosuchtable` and with `frequencies` in a feed without it.

A WARNING rather than an error, unlike the validator's other three codes: an untranslatable
row is a wasted row, not a broken reference.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import translations
from gtfs_validator.rules.registry import file_rule

CODE = "translation_unknown_table_name"


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    rows = translations.rows_of(feed)
    if translations.first_pass_failed(rows):
        return
    for row in rows:
        parent = translations.parent_filename(row)
        if translations.key_columns(parent) is not None and not feed.is_missing(parent):
            continue
        yield Notice(
            CODE,
            Severity.WARNING,
            {
                "csvRowNumber": row["_row_number"],
                "tableName": row.get(translations.TABLE_NAME) or "",
            },
        )
