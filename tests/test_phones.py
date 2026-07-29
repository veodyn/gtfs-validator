"""The phone port is tested against measured libphonenumber behaviour.

tests/data/phone_oracle.json records what the real
PhoneNumberUtil.isPossibleNumber(value, region) says for every case, produced by
tools/build_phone_oracle.py running against the bundled implementation in the
pinned jar. The first version of this port was a length check over a probed table,
which read 83 of these 308 cases wrong: isPossibleNumber parses before it
measures, and parse() rewrites the number repeatedly on the way.
"""

import json
from pathlib import Path

import pytest

from gtfs_validator.fieldtypes.phones import is_possible_phone_number

ORACLE = json.loads((Path(__file__).parent / "data" / "phone_oracle.json").read_text())["possible"]

# The port uppercases the region before use, so a lowercase code is scored against
# the jar's uppercase row. ZZ, QQ and the empty region are excluded on purpose:
# the fixture holds the raw libphonenumber verdict, while the port applies
# upstream's unknown-country gate and returns True for all three. Those are
# covered by the gate tests below.
GATED_REGIONS = {"US": "US", "GB": "GB", "FR": "FR", "DE": "DE", "AU": "AU", "AQ": "AQ", "us": "US"}

CASES = [
    (region, value, expected)
    for region, oracle_region in sorted(GATED_REGIONS.items())
    for value, expected in sorted(ORACLE[oracle_region].items())
]


@pytest.mark.parametrize(("region", "value", "expected"), CASES)
def test_matches_libphonenumber(region, value, expected):
    assert is_possible_phone_number(value, region) is expected


def test_the_oracle_is_not_trivially_one_sided():
    verdicts = {expected for _, _, expected in CASES}
    assert verdicts == {True, False}
    assert len(CASES) > 300


def test_unknown_country_skips_validation_entirely():
    # With -c ZZ or a non-ISO code, upstream returns before validating, so nothing
    # can fire. The gate must precede the plus branch: even an impossible +
    # number is silent. Measured end to end through the jar CLI.
    for region in ("ZZ", "zz", "QQ", ""):
        assert is_possible_phone_number("+1 5", region), region
        assert is_possible_phone_number("123", region), region
        assert is_possible_phone_number("nonsense", region), region


def test_country_without_phone_metadata_still_validates():
    # AQ is a real ISO country with no libphonenumber metadata, so it passes the
    # gate and then fails parsing: without a supported region a national number
    # has no country code to resolve, while a + number carries its own.
    assert not is_possible_phone_number("123", "AQ")
    assert is_possible_phone_number("+1 202-555-0173", "AQ")
    assert not is_possible_phone_number("+1 5", "AQ")


def test_the_quirks_that_motivate_the_port():
    # Each of these was wrong under the length-table model that preceded this one.
    assert is_possible_phone_number("12025550173", "US")  # national prefix stripped
    assert not is_possible_phone_number("17654321", "US")  # but only when it helps
    assert is_possible_phone_number("1-800-FLOWERS", "US")  # vanity letters are digits
    assert is_possible_phone_number("2025550173x42", "US")  # extension stripped
    assert is_possible_phone_number("011 44 20 7946 0958", "US")  # US dialling prefix
    assert not is_possible_phone_number("0012025550173", "US")  # but 00 is not one
    assert not is_possible_phone_number("+999 12345", "US")  # unassigned calling code
    assert not is_possible_phone_number("+abc1 202-555-0173", "US")  # not viable at all


def _in_script(digits: str, base: int) -> str:
    """Rewrite ASCII digits into another Unicode decimal script.

    Written as code points rather than literals: the glyphs are confusable with
    ASCII digits, and a test that silently used the wrong ones would assert
    nothing.
    """
    return "".join(chr(base + int(c)) if c.isdigit() else c for c in digits)


ARABIC_INDIC, DEVANAGARI, FULLWIDTH = 0x0660, 0x0966, 0xFF10


def test_every_unicode_decimal_digit_counts():
    # normalizeDigitsOnly folds any Nd character, so a stray Arabic-Indic digit
    # lengthens the number rather than vanishing from it.
    assert not is_possible_phone_number("+1 202-555-0173" + chr(ARABIC_INDIC + 1), "US")
    assert is_possible_phone_number(_in_script("2025550173", ARABIC_INDIC), "US")
    assert is_possible_phone_number(_in_script("2025550173", DEVANAGARI), "US")
    assert is_possible_phone_number("\uff0b" + _in_script("12025550173", FULLWIDTH), "US")


def test_the_input_ceiling_is_measured_in_utf16_units():
    # parse() rejects an input over 250 characters before extracting anything, and
    # Java measures that in UTF-16 code units, so an astral character counts twice.
    # Measured against the jar: 121 unicorns before a valid US number is 252 units
    # and impossible, while 119 is 248 and possible.
    number = "2025550173"
    assert not is_possible_phone_number("\U0001f984" * 121 + number, "US")
    assert is_possible_phone_number("\U0001f984" * 119 + number, "US")


def test_rfc3966_parameters_are_stripped_before_the_viability_check():
    # buildNationalNumberForParsing runs first, so a "tel:" URI's parameters never
    # reach the viability pattern. A phone-context holding a calling code joins
    # the number; a domain one is dropped. Measured: this build has no
    # phone-context validity check, so an absurd context is ignored, not fatal.
    assert is_possible_phone_number("tel:202-555-0173;phone-context=example.com", "US")
    assert is_possible_phone_number("tel:202-555-0173;phone-context=!!!", "US")
    assert is_possible_phone_number("tel:202-555-0173;isub=12345", "US")
    assert is_possible_phone_number("202-555-0173;phone-context=example.com", "US")
    # A context carrying "+1" is prepended, so this parses through calling code 1.
    assert is_possible_phone_number("tel:202-555-0173;phone-context=+1", "US")
    # And when it is, the digits count: "99" plus the context is 11 national.
    assert not is_possible_phone_number("tel:99;phone-context=+1202555017", "US")


def test_the_second_number_marker_is_case_sensitive():
    # SECOND_NUMBER_START_PATTERN is compiled with no flags, unlike EXTN_PATTERN,
    # so "/x" truncates and "/X" does not. Compiling every dumped pattern case
    # insensitively silently accepted the second form.
    assert is_possible_phone_number("2025550173/x1234567890", "US")
    assert not is_possible_phone_number("2025550173/X1234567890", "US")


def test_a_supplementary_plane_digit_is_not_a_digit():
    # normalizeDigitsOnly iterates UTF-16 code units, so an Osmanya digit arrives
    # as two surrogate halves and Character.digit rejects both. Iterating Python
    # code points folds it instead and turns this into a valid US number.
    osmanya = _in_script("2025550173", 0x104A0)
    assert not is_possible_phone_number(osmanya, "US")
    assert not is_possible_phone_number("+1" + osmanya, "US")
    assert is_possible_phone_number("2025550173", "US")


def test_the_vanity_path_drops_every_non_ascii_digit():
    # ALPHA_PHONE_MAPPINGS holds the 26 letters plus the ASCII digits, 36 entries.
    # Three letters put the number on that path, where a fullwidth or Arabic-Indic
    # digit is dropped rather than folded, even though the digits-only path keeps
    # it. Reconstructing the map from libphonenumber's wider digit set inverts this.
    assert is_possible_phone_number("1234567ABC", "US")
    assert not is_possible_phone_number(_in_script("1234567", FULLWIDTH) + "ABC", "US")
    assert not is_possible_phone_number(_in_script("1234567", ARABIC_INDIC) + "ABC", "US")
    # Without the letters the same digits are folded and the number is possible.
    assert is_possible_phone_number(_in_script("2025550173", FULLWIDTH), "US")


def test_an_unresolvable_calling_code_after_a_plus_is_retried():
    # parseHelper catches INVALID_COUNTRY_CODE and tries again with the plus
    # removed, which lets the default region's dialling prefix read the digits:
    # under US, "+011 44 ..." is a GB number reached through the US IDD "011".
    assert is_possible_phone_number("+011 44 20 7946 0958", "US")
    assert is_possible_phone_number("+011442079460958", "US")
    assert is_possible_phone_number("+00 44 20 7946 0958", "GB")
    # The retry is not a blanket second chance: a code that still resolves to
    # nothing stays impossible, in every region.
    for region in ("US", "GB", "DE", "AU"):
        assert not is_possible_phone_number("+999 12345", region), region
        assert not is_possible_phone_number("+0 12345", region), region
    # And without a supported region there is no dialling prefix to retry with.
    assert not is_possible_phone_number("+011 44 20 7946 0958", "AQ")
