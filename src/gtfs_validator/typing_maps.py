"""The single FieldType -> behaviour mappings for the typing stage.

This module owns the one and only mapping from a field type to its parser and to the
notice code its parse failure emits. Do not add a second one anywhere else;
`typing_compiled` binds these into per-field closures and `typing_stage` runs them.
"""

from __future__ import annotations

from gtfs_validator.fieldtypes import refdata, scalars
from gtfs_validator.fieldtypes.emails import is_valid_email
from gtfs_validator.fieldtypes.urls import is_valid_url
from gtfs_validator.schema import FieldType

# A BigDecimal (DECIMAL, CURRENCY_AMOUNT) that fails to parse draws invalid_float,
# because upstream's RowParser.asDecimal uses InvalidFloatNotice.
# invalid_currency_amount is not a parse failure at all; it is a scale check applied
# after parsing, in typing_postpass.
PARSE_NOTICE = {
    FieldType.COLOR: "invalid_color",
    FieldType.DATE: "invalid_date",
    FieldType.TIME: "invalid_time",
    FieldType.INTEGER: "invalid_integer",
    FieldType.FLOAT: "invalid_float",
    FieldType.LATITUDE: "invalid_float",
    FieldType.LONGITUDE: "invalid_float",
    FieldType.DECIMAL: "invalid_float",
    FieldType.CURRENCY_AMOUNT: "invalid_float",
    FieldType.CURRENCY_CODE: "invalid_currency",
    FieldType.LANGUAGE_CODE: "invalid_language_code",
    FieldType.TIMEZONE: "invalid_timezone",
}

PARSERS = {
    FieldType.COLOR: scalars.parse_color,
    FieldType.DATE: scalars.parse_date,
    FieldType.TIME: scalars.parse_time,
    FieldType.INTEGER: scalars.parse_integer,
    FieldType.FLOAT: scalars.parse_float,
    FieldType.LATITUDE: scalars.parse_float,
    FieldType.LONGITUDE: scalars.parse_float,
    FieldType.DECIMAL: scalars.parse_decimal,
    FieldType.CURRENCY_AMOUNT: scalars.parse_decimal,
    FieldType.CURRENCY_CODE: refdata.parse_currency_code,
    FieldType.LANGUAGE_CODE: refdata.parse_language_code,
    FieldType.TIMEZONE: refdata.parse_timezone,
}

# ID and TEXT never fail to parse; URL, EMAIL and PHONE_NUMBER validate in place
# and keep the original string rather than nulling the cell.
PASSTHROUGH_TYPES = frozenset({FieldType.ID, FieldType.TEXT})
VALIDATED_TYPES = frozenset({FieldType.URL, FieldType.EMAIL, FieldType.PHONE_NUMBER})
VALIDATORS = {
    FieldType.URL: (is_valid_url, "invalid_url"),
    FieldType.EMAIL: (is_valid_email, "invalid_email"),
}

# The types whose out-of-range notice carries the parsed value rather than a double.
EXACT_REPORT_TYPES = frozenset({FieldType.INTEGER, FieldType.DECIMAL, FieldType.CURRENCY_AMOUNT})
