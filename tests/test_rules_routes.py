"""The five routes.txt entity rules, asserted against measured jar output.

Every expected value here came from running the jar on a routes.txt carrying
sixteen shapes. Where a value looks wrong it is upstream's, and AGENTS.md
applies: read the Java before fixing it.
"""

import datetime

from gtfs_validator.context import Context
from gtfs_validator.rules import registry

CTX = Context(date=datetime.date(2026, 7, 24), country_code="US")


def fire(code, row):
    """Run one rule over one row and return the notices it produced."""
    registry.load_rules()
    return list(registry.REGISTRY[code].func(row, CTX))


def route(**fields):
    row = {
        "route_id": "R",
        "route_short_name": None,
        "route_long_name": None,
        "route_desc": None,
        "route_color": None,
        "route_text_color": None,
        "_row_number": 2,
    }
    row.update(fields)
    return row


def test_a_route_with_neither_name_is_reported():
    notices = fire("route_both_short_and_long_name_missing", route(route_id="R1"))
    assert [n.context for n in notices] == [{"routeId": "R1", "csvRowNumber": 2}]


def test_a_route_with_one_name_is_not_reported():
    assert fire("route_both_short_and_long_name_missing", route(route_short_name="N")) == []


def test_a_short_name_over_twelve_characters_is_reported():
    notices = fire(
        "route_short_name_too_long",
        route(route_id="R2", route_short_name="ABCDEFGHIJKLM", _row_number=3),
    )
    assert [n.context for n in notices] == [
        {"routeId": "R2", "csvRowNumber": 3, "routeShortName": "ABCDEFGHIJKLM"}
    ]


def test_a_twelve_character_short_name_is_not_reported():
    # The cap is "longer than 12", not "12 or longer". Measured: the jar reports
    # the 13-character R2 and says nothing about the 12-character R2b.
    assert fire("route_short_name_too_long", route(route_short_name="ABCDEFGHIJKL")) == []


def test_a_long_name_starting_with_the_short_name_is_reported():
    notices = fire(
        "route_long_name_contains_short_name",
        route(route_id="R3", route_short_name="N", route_long_name="N Judah", _row_number=5),
    )
    assert [n.context for n in notices] == [
        {
            "routeId": "R3",
            "csvRowNumber": 5,
            "routeShortName": "N",
            "routeLongName": "N Judah",
        }
    ]


def test_a_long_name_merely_prefixed_by_the_short_name_is_not_reported():
    # "NJudah" leaves a remainder of "Judah", which starts with none of the
    # separators, so it is a different name rather than a repetition.
    assert (
        fire(
            "route_long_name_contains_short_name",
            route(route_short_name="N", route_long_name="NJudah"),
        )
        == []
    )


def test_a_long_name_equal_to_the_short_name_is_reported():
    # The remainder is empty, which the check accepts before applying the regex.
    notices = fire(
        "route_long_name_contains_short_name",
        route(route_short_name="Express", route_long_name="Express"),
    )
    assert len(notices) == 1


def test_the_prefix_test_ignores_case():
    notices = fire(
        "route_long_name_contains_short_name",
        route(route_short_name="n", route_long_name="N Judah"),
    )
    assert len(notices) == 1


def test_the_optional_leading_space_does_not_make_the_separator_optional():
    # "^\\s?[\\s\\-\\(\\)].*" reads as though a separator were required after at
    # most one space, but the \\s? is optional, so a remainder beginning with a
    # single space satisfies the class itself. Measured: the jar reports "N x
    # Judah" against short name "N", which a stricter reading would not.
    for long_name in ("N Judah", "N  Judah", "N(Judah)", "N x Judah", "6 - ML King"):
        short = "6" if long_name.startswith("6") else "N"
        notices = fire(
            "route_long_name_contains_short_name",
            route(route_short_name=short, route_long_name=long_name),
        )
        assert len(notices) == 1, long_name


def test_a_description_equal_to_the_short_name_names_the_short_field():
    notices = fire(
        "same_name_and_description_for_route",
        route(
            route_id="R7",
            route_short_name="X",
            route_long_name="Long Name",
            route_desc="x",
            _row_number=9,
        ),
    )
    assert [n.context for n in notices] == [
        {
            "csvRowNumber": 9,
            "routeId": "R7",
            "routeDesc": "x",
            "specifiedField": "route_short_name",
        }
    ]


def test_a_description_equal_to_both_names_reports_only_the_short_one():
    # RouteNameValidator returns after the short-name branch fires. Measured: R9
    # carries short name, long name and description all equal to "X3" and draws
    # one notice naming route_short_name.
    notices = fire(
        "same_name_and_description_for_route",
        route(route_short_name="X3", route_long_name="X3", route_desc="x3"),
    )
    assert len(notices) == 1
    assert notices[0].context["specifiedField"] == "route_short_name"


def test_a_description_equal_to_the_long_name_names_the_long_field():
    notices = fire(
        "same_name_and_description_for_route",
        route(
            route_short_name="X2",
            route_long_name="Long Name 2",
            route_desc="long name 2",
        ),
    )
    assert [n.context["specifiedField"] for n in notices] == ["route_long_name"]


def test_low_contrast_colors_are_reported_in_html_form():
    # rec601Luma is (int)(0.30r + 0.59g + 0.11b) and the threshold is a difference
    # below 72. Colors render through GtfsColor.toHtmlColor, "#%06X". They arrive
    # as the packed integer the store holds rather than the feed's text: COLOR is
    # an INTEGER column, and writing this fixture with hex strings invented a row
    # shape the pipeline never produces.
    notices = fire(
        "route_color_contrast",
        route(
            route_id="R10",
            route_color=0xFFFFFF,
            route_text_color=0xFEFEFE,
            _row_number=12,
        ),
    )
    assert [n.context for n in notices] == [
        {
            "routeId": "R10",
            "csvRowNumber": 12,
            "routeColor": "#FFFFFF",
            "routeTextColor": "#FEFEFE",
        }
    ]


def test_high_contrast_colors_are_not_reported():
    assert (
        fire(
            "route_color_contrast",
            route(route_color=0x000000, route_text_color=0xFFFFFF),
        )
        == []
    )


def test_a_route_missing_either_color_is_not_reported():
    assert fire("route_color_contrast", route(route_color=0xFFFFFF)) == []


def test_a_short_name_is_measured_in_utf16_units():
    # String.length() counts code units, so seven astral characters are 14 and
    # over the cap of 12. Measured: the jar reports a route_short_name of seven
    # bus glyphs, which len() would see as 7 and let through.
    bus = "\U0001f68c"
    notices = fire("route_short_name_too_long", route(route_id="E1", route_short_name=bus * 7))
    assert notices[0].context["routeShortName"] == bus * 7
    assert fire("route_short_name_too_long", route(route_short_name=bus * 6)) == []


def test_the_separator_class_is_ascii_only():
    # Java's \s is ASCII-only unless UNICODE_CHARACTER_CLASS is set, and upstream
    # does not set it. Measured: the jar reports the ordinary-space spelling and
    # not the no-break-space one, which Python's \s would otherwise match.
    no_break_space = "\u00a0"
    assert (
        fire(
            "route_long_name_contains_short_name",
            route(route_short_name="N", route_long_name=f"N{no_break_space}Judah"),
        )
        == []
    )
    assert (
        len(
            fire(
                "route_long_name_contains_short_name",
                route(route_short_name="N", route_long_name="N Judah"),
            )
        )
        == 1
    )


def test_a_description_is_compared_with_java_case_rules():
    # equalsIgnoreCase, not casefold: the sharp-s spelling differs in length in
    # code units and is not reported, while the plain spelling is.
    sharp_s = "ß"
    assert (
        fire(
            "same_name_and_description_for_route",
            route(route_short_name=f"Stra{sharp_s}e", route_desc="STRASSE"),
        )
        == []
    )
    assert (
        len(
            fire(
                "same_name_and_description_for_route",
                route(route_short_name="Strasse", route_desc="STRASSE"),
            )
        )
        == 1
    )


def test_a_line_terminator_in_the_remainder_is_not_a_separator():
    # Java's String.matches anchors both ends, so the trailing ".*" must consume
    # the whole remainder, and Java's "." rejects five line terminators. Carriage
    # return and line feed draw new_line_in_value and never reach a rule; the
    # other three do. Measured: the jar reports none of these three and reports
    # the plain-space control.
    for terminator in ("\u0085", "\u2028", "\u2029"):
        assert (
            fire(
                "route_long_name_contains_short_name",
                route(route_short_name="N", route_long_name=f"N {terminator}X"),
            )
            == []
        ), terminator
    assert (
        len(
            fire(
                "route_long_name_contains_short_name",
                route(route_short_name="N", route_long_name="N X"),
            )
        )
        == 1
    )


def test_a_description_matching_only_after_uppercasing_is_reported():
    # equalsIgnoreCase lowercases the uppercased pair, so the dotted capital I
    # equals "i". Measured against the jar.
    notices = fire(
        "same_name_and_description_for_route",
        route(route_short_name="\u0130", route_desc="i"),
    )
    assert len(notices) == 1
