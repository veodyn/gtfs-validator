"""Stage 3: turn a raw row into typed values and emit the field-level notices.

Mirrors upstream RowParser: a cell that fails to parse becomes null and the row
is still returned, because every downstream rule has to see it. Only an empty row
or a header/row length mismatch drops one, and that already happened in stage 2.

The FieldType -> parser and FieldType -> notice mappings live in `typing_maps`;
the per-field behaviour is bound once per table in `typing_compiled`, because
deciding it per cell was about a third of a large feed's whole run. The checks
that fire on a condition rather than a failed conversion live in typing_checks.
"""

from __future__ import annotations

from gtfs_validator.notices import Notice, NoticeContainer
from gtfs_validator.schema import TableSchema
from gtfs_validator.typing_compiled import ABSENT, compiled_cells
from gtfs_validator.typing_postpass import check_currency_amounts, check_ranges


def type_row(
    schema: TableSchema,
    row: dict,
    notices: NoticeContainer,
    country_code: str = "",
) -> dict[str, object] | None:
    """Type one row and, if it is clean, run its entity validators.

    Returns the typed row for storage, or None when the row carried an
    ERROR-severity notice. Upstream's CsvFileLoader excludes such a row from the
    container: it is not stored, not indexed, and its single-entity validators
    (mixed_case, the range checks, the currency-amount check) do not run. Its
    parse and warning notices are still reported. A clean row runs those
    validators and is returned.

    mixed_case is checked per cell but held until the whole row is known clean,
    because it fires mid-loop before the row's verdict is in.
    """
    row_number = int(row["_row_number"])
    typed: dict[str, object] = {"_row_number": row_number}
    mixed_case_pending: list[Notice] = []
    errors_before = notices.error_count()
    row_get = row.get
    for name, cell in compiled_cells(schema, country_code):
        typed[name] = cell(row_get(name, ABSENT), row_number, notices, mixed_case_pending)

    if notices.error_count() != errors_before:
        # The row produced an ERROR, so upstream drops it: no entity validators,
        # not added to the container. The cell notices above already fired.
        return None
    notices.add_all(mixed_case_pending)
    check_ranges(schema, typed, row_number, notices)
    check_currency_amounts(schema, typed, row_number, notices)
    return typed
