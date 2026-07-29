"""invalid_currency_amount is a scale check, not a parse failure.

Verified against the jar: fare_products amount 2.5 with USD (2 fraction digits)
is reported because its scale is 1, while 3 with JPY (0 digits) is not. A cell
that fails to parse as a decimal draws invalid_float instead.
"""

import pytest

from gtfs_validator.error_ids import AppError, ErrorIds
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.schema import Field, FieldType, Presence, TableSchema
from gtfs_validator.typing_stage import type_row

FARE_PRODUCTS = TableSchema(
    "fare_products.txt",
    Presence.OPTIONAL,
    ("fare_product_id",),
    (
        Field("fare_product_id", FieldType.ID, Presence.REQUIRED),
        Field(
            "amount",
            FieldType.CURRENCY_AMOUNT,
            Presence.REQUIRED,
            currency_field="currency",
            bounds="NON_NEGATIVE",
        ),
        Field("currency", FieldType.CURRENCY_CODE, Presence.REQUIRED),
    ),
)


def codes(notices):
    return [n.code for g in notices.grouped().values() for n in g]


def only(notices, code):
    return next(n for g in notices.grouped().values() for n in g if n.code == code)


def test_scale_mismatch_is_reported():
    notices = NoticeContainer()
    type_row(
        FARE_PRODUCTS,
        {"_row_number": 2, "fare_product_id": "FP1", "amount": "2.5", "currency": "USD"},
        notices,
    )
    context = only(notices, "invalid_currency_amount").context
    assert context["currencyCode"] == "USD"
    assert context["fieldName"] == "amount"
    assert context["fieldValue"] == "2.5"


def test_matching_scale_is_silent():
    notices = NoticeContainer()
    type_row(
        FARE_PRODUCTS,
        {"_row_number": 2, "fare_product_id": "FP1", "amount": "2.50", "currency": "USD"},
        notices,
    )
    assert codes(notices) == []


def test_zero_fraction_currency_accepts_an_integer_amount():
    notices = NoticeContainer()
    type_row(
        FARE_PRODUCTS,
        {"_row_number": 2, "fare_product_id": "FP1", "amount": "3", "currency": "JPY"},
        notices,
    )
    assert codes(notices) == []


FARE_ATTRIBUTES = TableSchema(
    "fare_attributes.txt",
    Presence.OPTIONAL,
    ("fare_id",),
    (
        Field("fare_id", FieldType.ID, Presence.REQUIRED),
        Field("price", FieldType.DECIMAL, Presence.REQUIRED, bounds="NON_NEGATIVE"),
    ),
)


def test_negative_decimal_fires_number_out_of_range_and_excludes_the_row():
    # Measured against the jar: a negative fare price draws number_out_of_range
    # with fieldType "non-negative decimal" and the value rendered as a double
    # (-1.5), and the ERROR excludes the row. Regression: returning a Decimal from
    # parse_decimal skipped the numeric bounds branch, so the notice never fired.
    notices = NoticeContainer()
    typed = type_row(
        FARE_ATTRIBUTES,
        {"_row_number": 2, "fare_id": "F1", "price": "-1.5"},
        notices,
    )
    notice = only(notices, "number_out_of_range")
    assert notice.context["fieldType"] == "non-negative decimal"
    assert notice.context["fieldValue"] == -1.5
    assert typed is None


def test_currency_amount_with_negative_amount_is_number_out_of_range():
    # amount is CURRENCY_AMOUNT and NON_NEGATIVE, so -2.50 is a bounds error, the
    # kind still reads "decimal", and the double render drops the trailing zero.
    notices = NoticeContainer()
    type_row(
        FARE_PRODUCTS,
        {"_row_number": 2, "fare_product_id": "FP1", "amount": "-2.50", "currency": "USD"},
        notices,
    )
    notice = only(notices, "number_out_of_range")
    assert notice.context["fieldType"] == "non-negative decimal"
    assert notice.context["fieldValue"] == -2.5


def test_unparseable_amount_is_invalid_float_not_currency_amount():
    # A BigDecimal that fails to parse draws invalid_float (RowParser.asDecimal
    # uses InvalidFloatNotice), and the row is then excluded.
    notices = NoticeContainer()
    typed = type_row(
        FARE_PRODUCTS,
        {"_row_number": 2, "fare_product_id": "FP1", "amount": "1f", "currency": "USD"},
        notices,
    )
    assert codes(notices) == ["invalid_float"]
    assert typed is None


def test_exponent_form_is_rendered_as_a_plain_string():
    # Upstream stores BigDecimal.toPlainString(), so "1E+2" is reported as "100".
    # str(Decimal) keeps the exponent and would emit "1E+2". Measured against the
    # jar: fare_products amount 1E+2 in USD reports fieldValue "100", and 0.001E3
    # reports "1".
    for raw, expected in (("1E+2", "100"), ("0.001E3", "1"), ("2.5", "2.5")):
        notices = NoticeContainer()
        type_row(
            FARE_PRODUCTS,
            {"_row_number": 2, "fare_product_id": "P1", "amount": raw, "currency": "USD"},
            notices,
        )
        assert only(notices, "invalid_currency_amount").context["fieldValue"] == expected, raw


def test_exponent_outside_bigdecimal_range_is_a_parse_failure():
    # BigDecimal keeps its scale in an int, so both the exponent and the scale it
    # implies must fit in 32 bits. Measured against the jar: 1e2147483647 parses
    # and 1e2147483648 draws invalid_float, as does 1e-2147483648, whose scale
    # rather than exponent overflows.
    for raw in ("1e2147483648", "1e-2147483648"):
        notices = NoticeContainer()
        assert (
            type_row(
                FARE_PRODUCTS,
                {"_row_number": 2, "fare_product_id": "P1", "amount": raw, "currency": "USD"},
                notices,
            )
            is None
        )
        assert "invalid_float" in codes(notices), raw


def test_a_tiny_negative_decimal_is_still_negative():
    # checkBounds compares the BigDecimal, so -1e-400 is out of range for a NON_NEGATIVE field.
    # Rounding to a double first gives -0.0, which passes the predicate and keeps the row.
    #
    # The notice reports the BigDecimal, not the double. This test asserted "-0.0" and called it
    # settled; a review measured the jar and it reports -1E-400, the value itself. Rounding was
    # right for the *comparison* and wrong for the *report*, and asserting the rounded form here
    # is what made the defect look intended for six plans.
    notices = NoticeContainer()
    row = type_row(
        FARE_PRODUCTS,
        {"_row_number": 2, "fare_product_id": "P1", "amount": "-1e-400", "currency": "USD"},
        notices,
    )
    assert row is None
    notice = only(notices, "number_out_of_range")
    assert notice.context["fieldType"] == "non-negative decimal"
    assert str(notice.context["fieldValue"]) == "-1E-400"


def test_negative_zero_is_not_negative():
    # -0.00 compares equal to zero, so it passes NON_NEGATIVE, and its scale
    # matches USD's two fraction digits. The jar reports nothing for it.
    notices = NoticeContainer()
    type_row(
        FARE_PRODUCTS,
        {"_row_number": 2, "fare_product_id": "P1", "amount": "-0.00", "currency": "USD"},
        notices,
    )
    assert codes(notices) == []


def test_a_long_exponent_is_parsed_rather_than_crashing():
    # Java skips leading zeros in an exponent, so "1e" followed by five thousand
    # zeros is simply 1. Calling Python's int() on that text raises instead, and
    # the exception escaped typing and failed the whole table.
    notices = NoticeContainer()
    row = type_row(
        FARE_PRODUCTS,
        {
            "_row_number": 2,
            "fare_product_id": "P1",
            "amount": "1e" + "0" * 5000,
            "currency": "USD",
        },
        notices,
    )
    assert row is not None
    assert "invalid_float" not in codes(notices)


def test_negative_zero_renders_without_its_sign():
    # BigDecimal canonicalises zero's sign, so toPlainString gives "0.0" where
    # format(Decimal, "f") gives "-0.0". The scale still mismatches USD, so the
    # notice fires and its sample value is what diverges.
    notices = NoticeContainer()
    type_row(
        FARE_PRODUCTS,
        {"_row_number": 2, "fare_product_id": "P1", "amount": "-0.0", "currency": "USD"},
        notices,
    )
    assert only(notices, "invalid_currency_amount").context["fieldValue"] == "0.0"


def test_zero_with_a_negative_scale_renders_as_a_single_zero():
    # toPlainString short-circuits a zero whose scale is not positive: it returns
    # "0" rather than padding out the exponent. Without that case the size guard
    # sees billions of implied zeros and refuses to render at all, which drops the
    # whole table. Measured against the jar on fare_products in USD: rows carrying
    # 0E2147483646, 0E+100, 0, 0.0, -0E5 and 0E2147483647 all report
    # invalid_currency_amount, and every one of them has fieldValue "0" except
    # "0.0", whose scale is positive.
    for raw in ("0E2147483646", "0E+100", "0", "-0E5", "0E2147483647"):
        notices = NoticeContainer()
        type_row(
            FARE_PRODUCTS,
            {"_row_number": 2, "fare_product_id": "P1", "amount": raw, "currency": "USD"},
            notices,
        )
        assert only(notices, "invalid_currency_amount").context["fieldValue"] == "0", raw


def test_zero_with_an_unrenderable_positive_scale_is_still_refused():
    # The short-circuit is scale-signed, not value-based. A zero with a huge
    # positive scale really does render as "0." plus two billion zeros in Java, so
    # it hits the same OutOfMemoryError as a non-zero value does and the guard
    # must still fire.
    notices = NoticeContainer()
    with pytest.raises(AppError) as caught:
        type_row(
            FARE_PRODUCTS,
            {
                "_row_number": 2,
                "fare_product_id": "P1",
                "amount": "0E-2147483647",
                "currency": "USD",
            },
            notices,
        )
    assert caught.value.id is ErrorIds.TYPE_DECIMAL_UNRENDERABLE
