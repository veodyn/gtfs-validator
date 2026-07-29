"""Java string semantics Python's look-alikes do not reproduce."""

from gtfs_validator.javatext import (
    equals_ignore_case,
    is_blank,
    trim,
    utf16_length,
    utf16_units,
)

BUS = "\U0001f68c"  # an astral character, two UTF-16 units
SHARP_S = "ß"
NO_BREAK_SPACE = "\u00a0"


def test_an_astral_character_is_two_units():
    assert utf16_length(BUS) == 2
    assert utf16_length(BUS * 7) == 14
    assert len(BUS * 7) == 7


def test_utf16_units_splits_an_astral_character_into_surrogates():
    assert utf16_units(BUS) == [0xD83D, 0xDE8C]
    assert utf16_units("N") == [0x4E]


def test_equals_ignore_case_matches_plain_ascii_folding():
    assert equals_ignore_case("Strasse", "STRASSE")
    assert equals_ignore_case("main st", "Main St")
    assert not equals_ignore_case("Main St", "Elm St")


def test_equals_ignore_case_rejects_a_length_change_from_folding():
    # casefold turns the sharp s into "ss" and would equate these. Java compares
    # lengths in code units first, and 6 is not 7. Measured: the jar reports
    # same_name_and_description_for_route for the "Strasse" spelling and says
    # nothing for this one.
    assert f"Stra{SHARP_S}e".casefold() == "STRASSE".casefold()
    assert not equals_ignore_case(f"Stra{SHARP_S}e", "STRASSE")


def test_equals_ignore_case_leaves_a_sharp_s_alone():
    # Character.toUpperCase returns the char unchanged when its uppercase form is
    # not a single character, so a sharp s only matches a sharp s.
    assert equals_ignore_case(f"Stra{SHARP_S}e", f"STRA{SHARP_S}E")


def test_trim_keeps_a_no_break_space():
    # String.trim removes code units at or below U+0020, so it keeps a no-break
    # space that Python's str.strip removes. Measured: for a feed_contact_email
    # of one no-break space the jar reports invalid_email carrying that
    # character and no leading_or_trailing_whitespaces at all.
    assert trim(NO_BREAK_SPACE) == NO_BREAK_SPACE
    assert NO_BREAK_SPACE.strip() == ""


def test_trim_removes_every_unit_below_the_space():
    # Java's boundary is the code unit's value, not a whitespace test, so a
    # control character goes even though it is not whitespace to anyone.
    assert trim(" hello ") == "hello"
    assert trim("\u0001hello\u0002") == "hello"
    assert trim("   ") == ""
    assert trim("a b") == "a b"


def test_is_blank_excludes_the_non_breaking_spaces():
    # Character.isWhitespace is a third rule again: an em space is whitespace to
    # it but above trim's ceiling, and a no-break space is neither.
    assert is_blank(" \t\n")
    assert is_blank("\u2003")
    assert not is_blank(NO_BREAK_SPACE)
    assert not is_blank("a")
    assert is_blank("")


DOTTED_I = "\u0130"  # LATIN CAPITAL LETTER I WITH DOT ABOVE
DESERET_UP = "\U00010400"
DESERET_LOW = "\U00010428"


def test_equals_ignore_case_lowercases_the_uppercased_pair():
    # Java's third test is toLowerCase(toUpperCase(c)), not toLowerCase(c). The
    # dotted capital I and "i" have different uppercase forms and only meet after
    # uppercasing, so lowercasing the originals misses them. Measured: the jar
    # reports same_name_and_description_for_route for this pair.
    assert equals_ignore_case(DOTTED_I, "i")
    # Python's full lowercase adds a combining dot, so str.lower disagrees.
    assert DOTTED_I.lower() != "i"


def test_equals_ignore_case_pairs_supplementary_code_points():
    # A Deseret capital and its small form are a surrogate pair each and their
    # low surrogates differ, so a per-code-unit comparison rejects them.
    # Measured: the jar treats them as equal, so the comparison is per code point.
    assert equals_ignore_case(DESERET_UP, DESERET_LOW)
    assert utf16_units(DESERET_UP)[1] != utf16_units(DESERET_LOW)[1]


def test_equals_ignore_case_still_needs_equal_unit_length():
    assert not equals_ignore_case(DESERET_UP, "ab")


def test_double_string_matches_java_for_the_values_a_feature_id_can_hold():
    """Every value here was measured on the jar through a feature id in a notice context.

    The scientific form has to be constructed rather than taken from `repr`: 1e-4 reprs as
    "0.0001" and 1e7 as "10000000.0", neither carrying an exponent, and a first version that
    reformatted only when it saw an "e" left both wrong.
    """
    from gtfs_validator.javatext import double_string

    assert double_string(7) == "7.0"
    assert double_string(8.5) == "8.5"
    assert double_string(1e3) == "1000.0"
    assert double_string(1e-3) == "0.001"
    assert double_string(1e-4) == "1.0E-4"
    assert double_string(1e7) == "1.0E7"
    assert double_string(1.5e-5) == "1.5E-5"
    assert double_string(1.7976931348623157e308) == "1.7976931348623157E308"
    assert double_string(-0.0) == "-0.0"
    assert double_string(0.0) == "0.0"


def test_double_string_leaves_the_minimum_subnormal_to_a_divergence():
    """JDK 17 prints "4.9E-324" and this prints "5.0E-324", which is divergence 14.

    Asserted rather than skipped so the day the pin moves past JDK 19, or FloatingDecimal is
    ported, this test fails and the entry gets deleted with it.
    """
    from gtfs_validator.javatext import double_string

    assert double_string(5e-324) == "5.0E-324"


def test_utf16_length_is_unchanged_by_the_ascii_short_circuit():
    """The fast path must agree with the per-character count on every shape of input.

    `utf16_length` is on the hot path for every feed: profiling a real 997,334-row feed showed it
    called 6,160,072 times, with its inner generator running 172,105,692 times for about a seventh
    of the whole run. The optimisation is an `isascii()` short circuit plus a single encode, so what
    needs pinning is that it did not change any answer.
    """
    cases = [
        "",
        "plain ascii",
        "café",  # Latin-1 supplement, still one UTF-16 unit each
        "中文",  # BMP, one unit each
        "\U0001d400",  # astral, two units
        "a\U0001d400b",  # mixed
        "\U0001d400" * 7,  # the route_short_name_too_long case: 7 code points, 14 units
        "�",  # the replacement character a bad decode leaves behind
    ]
    for value in cases:
        expected = sum(2 if ord(char) > 0xFFFF else 1 for char in value)
        assert utf16_length(value) == expected, repr(value)
