"""Stage 3 checks that run once per row after every cell has been typed.

The range checks compare two already-parsed fields, and the currency-amount check
compares a parsed amount against its sibling currency, so both need the whole
typed row rather than a single cell. They live here to keep typing_stage focused
on the per-cell dispatch.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from importlib.resources import files

from gtfs_validator.error_ids import AppError, ErrorIds
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.schema import FieldType, TableSchema


@lru_cache(maxsize=1)
def _currency_fraction_digits() -> dict[str, int]:
    raw = json.loads(files("gtfs_validator.data").joinpath("currencies.json").read_text())
    return raw["fraction_digits"]


def _render(field_type: FieldType, value: object) -> str:
    """Reproduce the Java type's toString for a range notice's displayed value."""
    if field_type is FieldType.TIME and isinstance(value, int):
        return f"{value // 3600:02d}:{value % 3600 // 60:02d}:{value % 60:02d}"
    if field_type is FieldType.DATE and isinstance(value, tuple):
        return "{:04d}{:02d}{:02d}".format(*value)
    return str(value)


def _entity_id(schema: TableSchema, typed: dict) -> str | None:
    """The single-column primary key value, which upstream sends as entityId.

    Multi-column-key tables send no entityId, matching EndRangeValidatorGenerator,
    which only emits it when hasSingleColumnPrimaryKey.
    """
    if len(schema.primary_key) != 1:
        return None
    value = typed.get(schema.primary_key[0])
    return None if value is None else str(value)


def check_ranges(
    schema: TableSchema, typed: dict, row_number: int, notices: NoticeContainer
) -> None:
    entity_id = _entity_id(schema, typed)
    for field in schema.fields:
        if not field.end_range:
            continue
        end_name, allow_equal = field.end_range
        start, end = typed.get(field.name), typed.get(end_name)
        if start is None or end is None:
            continue
        end_field = schema.field(end_name)
        start_str = _render(field.type, start)
        end_str = _render(end_field.type, end) if end_field else str(end)
        base: dict[str, object] = {
            "filename": schema.filename,
            "csvRowNumber": row_number,
        }
        if entity_id is not None:
            base["entityId"] = entity_id
        if start == end and not allow_equal:
            notices.add(
                Notice(
                    "start_and_end_range_equal",
                    Severity.ERROR,
                    {
                        **base,
                        "startFieldName": field.name,
                        "endFieldName": end_name,
                        "value": start_str,
                    },
                )
            )
        elif start > end:
            notices.add(
                Notice(
                    "start_and_end_range_out_of_order",
                    Severity.ERROR,
                    {
                        **base,
                        "startFieldName": field.name,
                        "startValue": start_str,
                        "endFieldName": end_name,
                        "endValue": end_str,
                    },
                )
            )


# java.lang.String's maximum length. A BigDecimal whose plain form is longer
# cannot be rendered at all: the jar throws OutOfMemoryError ("too large to fit
# in a String") and reports a thread_execution_error instead of a notice.
# Measured: 1e1000000000 renders and produces a 1 GB report, 1e2147483647 does not.
MAX_JAVA_STRING_LENGTH = 2147483647


def _plain_string(amount: Decimal) -> str:
    """BigDecimal.toPlainString, refusing a value Java could not render either.

    The length is computed from the exponent rather than discovered by rendering,
    because the whole point is not to materialise a multi-gigabyte string. Below
    the limit the string is produced however large it is, because that is what
    upstream does: a 1 GB report is absurd but it is the measured behaviour.
    """
    digits = len(amount.as_tuple().digits)
    exponent = amount.as_tuple().exponent
    # BigDecimal canonicalises zero's sign, so "-0.0" renders as "0.0". A value
    # that merely rounds to zero as a double keeps its sign: -1e-400 is signum -1.
    if amount == 0:
        # toPlainString short-circuits a zero whose scale is not positive rather
        # than padding it out, so 0E+2147483646 is one character and not two
        # gigabytes. The short-circuit is on the scale's sign, not the value, so
        # a zero with a huge positive scale still falls through to the guard.
        if exponent >= 0:
            return "0"
        amount = abs(amount)
    # Integral form pads with zeros; fractional form needs a "0." lead-in when the
    # exponent outruns the digits. One more character for a sign.
    length = digits + exponent if exponent >= 0 else max(digits, -exponent + 1) + 1
    if length + 1 > MAX_JAVA_STRING_LENGTH:
        raise AppError(
            ErrorIds.TYPE_DECIMAL_UNRENDERABLE,
            "decimal is too large to render as a plain string",
            {"exponent": exponent, "digits": digits},
        )
    return format(amount, "f")


def check_currency_amounts(
    schema: TableSchema, typed: dict, row_number: int, notices: NoticeContainer
) -> None:
    """invalid_currency_amount: the amount's scale must match its currency.

    Not a parse failure. Upstream's generated CurrencyAmountValidator fires when
    amount.scale() differs from the sibling currency's default fraction digits,
    so USD 2.5 (scale 1, wants 2) is reported while JPY 3 (scale 0, wants 0) is not.
    """
    for field in schema.fields:
        if field.type is not FieldType.CURRENCY_AMOUNT or not field.currency_field:
            continue
        amount = typed.get(field.name)
        currency = typed.get(field.currency_field)
        if not isinstance(amount, Decimal) or currency is None:
            continue
        fraction_digits = _currency_fraction_digits().get(currency)
        if fraction_digits is None:
            continue
        if -amount.as_tuple().exponent != fraction_digits:
            notices.add(
                Notice(
                    "invalid_currency_amount",
                    Severity.ERROR,
                    {
                        "filename": schema.filename,
                        "csvRowNumber": row_number,
                        "currencyCode": currency,
                        "fieldName": field.name,
                        # BigDecimal.toPlainString, not toString: upstream never
                        # emits exponent notation, so "1E+2" is reported as "100".
                        # format(d, "f") is the Python spelling of that.
                        "fieldValue": _plain_string(amount),
                    },
                )
            )
