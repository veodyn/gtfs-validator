import json
from pathlib import Path

import pytest

from gtfs_validator.fieldtypes.refdata import (
    ParseError,
    parse_currency_code,
    parse_language_code,
    parse_timezone,
)

LANGUAGE_ORACLE = json.loads((Path(__file__).parent / "data" / "language_oracle.json").read_text())[
    "tags"
]


@pytest.mark.parametrize(("tag", "expected"), sorted(LANGUAGE_ORACLE.items()))
def test_language_grammar_matches_locale_builder(tag, expected):
    # Locale.Builder accepts any well-formed BCP 47 tag, so this is a grammar
    # check and not a registry lookup: "xx" is unassigned but valid.
    assert (not isinstance(parse_language_code(tag), ParseError)) is expected


def test_the_language_oracle_covers_both_verdicts():
    assert set(LANGUAGE_ORACLE.values()) == {True, False}


@pytest.mark.parametrize("value", ["America/New_York", "Europe/Amsterdam", "UTC"])
def test_timezone_accepts_tz_database_names(value):
    assert parse_timezone(value) == value


@pytest.mark.parametrize("value", ["", "Mars/Olympus", "america/new_york"])
def test_timezone_rejects_unknown_names(value):
    assert isinstance(parse_timezone(value), ParseError)


# Every pair oracled from the pinned JDK: `ZoneId.of(input).getId()`. Parsing is not
# enough, because the stored value is what a notice reports and what a rule compares:
# +0200 and +02:00 are one zone, and reporting the feed's spelling made
# inconsistent_agency_timezone fire where the jar stayed silent.
ZONE_IDS = {
    "+02:00": "+02:00",
    "+0200": "+02:00",
    "+2": "+02:00",
    "+02": "+02:00",
    "+020000": "+02:00",
    "+02:00:00": "+02:00",
    "+02:00:30": "+02:00:30",
    "+020030": "+02:00:30",
    "+00:00": "Z",
    "+0000": "Z",
    "+00": "Z",
    "-00:00": "Z",
    "Z": "Z",
    "-05:00": "-05:00",
    "-0500": "-05:00",
    "UTC+02:00": "UTC+02:00",
    "UTC-05:00": "UTC-05:00",
    "GMT+2": "GMT+02:00",
    "UT+2": "UT+02:00",
    "GMT+0": "GMT",
    "GMT-0": "GMT",
    "UTC+0": "UTC",
    "UT+0": "UT",
    "UTC": "UTC",
    "GMT": "GMT",
    # Region names, not prefixes over an offset: GMT0 is a real tzdb name, and
    # returning "GMT" for it would be a normalisation the jar does not do.
    "GMT0": "GMT0",
    "EST5EDT": "EST5EDT",
    "Etc/GMT+5": "Etc/GMT+5",
    "America/New_York": "America/New_York",
}


@pytest.mark.parametrize(("value", "expected"), sorted(ZONE_IDS.items()))
def test_timezone_normalises_to_the_zone_id(value, expected):
    assert parse_timezone(value) == expected


@pytest.mark.parametrize("value", ["UTC0", "EST", "+2:0", "02:00", "UTCZ", "+18:01", "+02:60"])
def test_timezone_rejects_what_zone_id_of_throws_on(value):
    assert isinstance(parse_timezone(value), ParseError)


def test_currency_is_case_sensitive_like_java():
    assert parse_currency_code("USD") == "USD"
    assert parse_currency_code("EUR") == "EUR"
    # Currency.getInstance("usd") throws IllegalArgumentException.
    assert isinstance(parse_currency_code("usd"), ParseError)
    assert isinstance(parse_currency_code("XYZ"), ParseError)
    assert isinstance(parse_currency_code(""), ParseError)


# Offset-form timezones, measured with ZoneId.of via jshell. ZoneOffset.of is not
# a shape check: it bounds hours at 18, minutes and seconds at 59, and 18:00:00,
# and it accepts a single-digit hour and the bare UTC/GMT/UT prefixes.
def _tz_ok(value):
    return not isinstance(parse_timezone(value), ParseError)


def test_offset_timezones_match_zoneid_of():
    for value in (
        "+2",
        "UTC+2",
        "GMT+2",
        "UT+2",
        "Z",
        "UTC",
        "GMT",
        "UT",
        "+02:00",
        "+0200",
        "+020000",
        "+02:00:00",
        "+18:00",
        "-05:00",
        "UTC+02:00",
        "UTC-05",
    ):
        assert _tz_ok(value), value


def test_out_of_range_offsets_are_rejected_like_zoneid_of():
    # A shape-only regex accepted all of these; ZoneId.of throws on every one.
    for value in ("+18:01", "+19:00", "+02:60", "+99:00", "+2:00", "+023", "+02:00:60", "z", "+"):
        assert not _tz_ok(value), value


def test_z_is_only_accepted_on_its_own():
    # ZoneId.of("UTCZ") throws: a suffix after UTC/GMT/UT must be a signed offset.
    assert _tz_ok("Z")
    for value in ("UTCZ", "GMTZ", "UTZ", "UTCz"):
        assert not _tz_ok(value), value
