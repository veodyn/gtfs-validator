import pytest

from gtfs_validator.fieldtypes.scalars import (
    ParseError,
    parse_color,
    parse_date,
    parse_decimal,
    parse_float,
    parse_integer,
    parse_time,
)


@pytest.mark.parametrize("value", ["FFFFFF", "000000", "abcdef", "01AB23"])
def test_color_accepts_six_hex_digits(value):
    assert not isinstance(parse_color(value), ParseError)


@pytest.mark.parametrize("value", ["FFF", "FFFFFFF", "GGGGGG", "", "#FFFFF"])
def test_color_rejects_anything_else(value):
    assert isinstance(parse_color(value), ParseError)


def test_color_returns_the_rgb_integer():
    assert parse_color("FFFFFF") == 0xFFFFFF
    assert parse_color("000000") == 0


def test_date_requires_a_real_calendar_date():
    assert parse_date("20260130") == (2026, 1, 30)
    assert isinstance(parse_date("20260230"), ParseError)  # February 30
    assert isinstance(parse_date("2026-01-30"), ParseError)  # wrong length
    assert isinstance(parse_date("202601"), ParseError)
    assert isinstance(parse_date("2026013a"), ParseError)


def test_time_allows_hours_past_midnight():
    # 25:30:00 is legal GTFS: a trip running past midnight of its service day.
    assert parse_time("25:30:00") == 25 * 3600 + 30 * 60
    assert parse_time("5:03:00") == 5 * 3600 + 3 * 60
    assert parse_time("100:00:00") == 100 * 3600


@pytest.mark.parametrize("value", ["12:60:00", "12:00:60", "12:0:00", "12:00", ""])
def test_time_rejects_malformed_values(value):
    assert isinstance(parse_time(value), ParseError)


def test_integer_uses_java_semantics_not_python():
    assert parse_integer("42") == 42
    assert parse_integer("-42") == -42
    assert parse_integer("+42") == 42


@pytest.mark.parametrize("value", ["1_000", " 5 ", "5.0", "", "0x1F", "٤٢"])
def test_integer_rejects_what_java_rejects(value):
    # Python's int() accepts underscores, surrounding whitespace, and Arabic-Indic
    # digits. Integer.parseInt accepts none of them, and the report counts
    # invalid_integer per feed, so matching Java exactly is the contract.
    assert isinstance(parse_integer(value), ParseError)


def test_float_accepts_java_double_literals():
    assert parse_float("1.5") == 1.5
    assert parse_float("1e3") == 1000.0
    assert parse_float("-0.5") == -0.5
    assert parse_float(".5") == 0.5
    assert parse_float("5.") == 5.0


@pytest.mark.parametrize("value", ["nan", "infinity", "1_0", " 1.5", "", "1,5"])
def test_float_rejects_what_java_rejects(value):
    assert isinstance(parse_float(value), ParseError)


def test_float_accepts_javas_spelling_of_the_specials():
    # Double.parseDouble accepts NaN and Infinity with exactly this casing.
    assert parse_float("NaN") != parse_float("NaN")  # NaN is not equal to itself
    assert parse_float("Infinity") == float("inf")


def test_decimal_rejects_the_specials_that_bigdecimal_rejects():
    assert parse_decimal("1.50") == 1.5
    assert isinstance(parse_decimal("NaN"), ParseError)
    assert isinstance(parse_decimal("Infinity"), ParseError)
