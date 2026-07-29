"""How a parsed value and a schema name become SQL: storage classes, binding, and quoting.

Split from `store` when that file passed the size limit. The division is by responsibility: this
module knows the mapping between our field types and SQLite's, and nothing about tables, statements
or streaming. `store` keeps the database.
"""

from __future__ import annotations

import re
from decimal import Decimal

from gtfs_validator.error_ids import AppError, ErrorIds
from gtfs_validator.schema import FieldType

BATCH_SIZE = 5_000
ROW_NUMBER_COLUMN = "_row_number"

# SQLite cannot bind a table or column name, so those are built into SQL text.
# Everything reaching that path comes from the generated schema registry rather
# than from the feed, and this makes that a checked property instead of a claim.
_SAFE_IDENTIFIER_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_.]*\Z")


def quote_identifier(name: str) -> str:
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise AppError(
            ErrorIds.STORE_UNSAFE_IDENTIFIER,
            "refusing to build SQL with an identifier that is not from the schema registry",
            {"identifier": name},
        )
    return f'"{name}"'


# SQLite storage class per field type. TIME is seconds since midnight and DATE is
# YYYYMMDD, both integers, so ordering comparisons in SQL are correct without a
# conversion step.
SQLITE_TYPE = {
    FieldType.INTEGER: "INTEGER",
    FieldType.ENUM: "INTEGER",
    FieldType.TIME: "INTEGER",
    FieldType.DATE: "INTEGER",
    FieldType.COLOR: "INTEGER",
    FieldType.FLOAT: "REAL",
    FieldType.LATITUDE: "REAL",
    FieldType.LONGITUDE: "REAL",
    # Decimals are stored as text so the exact value and scale survive; a REAL
    # column's numeric affinity would round "2.50" to 2.5 and lose the scale.
    FieldType.DECIMAL: "TEXT",
    FieldType.CURRENCY_AMOUNT: "TEXT",
}


def encode(field_type: FieldType, value: object) -> object:
    """Flatten a parsed value into something SQLite can bind.

    parse_date returns a (year, month, day) triple that becomes a YYYYMMDD int so
    SQL ordering is correct; parse_decimal returns a Decimal, which sqlite3
    cannot bind, so it is stored as its exact string form.
    """
    if value is None:
        return None
    if field_type is FieldType.DATE and isinstance(value, tuple):
        year, month, day = value
        return year * 10000 + month * 100 + day
    if isinstance(value, Decimal):
        return str(value)
    return value
