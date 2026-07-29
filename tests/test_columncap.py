"""Univocity's per-column character cap and the offsets its failure reports.

The offsets come from four probe feeds, each putting the over-long field somewhere different, and
they pin a formula rather than a single number: `charIndex` is the field's first character plus
the cap plus one. Guessing from one probe would have fitted `+ cap + 2` just as well, because that
feed's field happened to start one byte later than I first counted.
"""

from __future__ import annotations

import pytest

from gtfs_validator.columncap import UNLIMITED, ColumnCapScanner, ColumnTooLong


def scan(text: str, cap: int = 8) -> list[str]:
    """Feed a whole document through the scanner as csv.reader would."""
    return list(ColumnCapScanner(cap).scan(text.splitlines(keepends=True)))


def test_ordinary_input_passes_through_unchanged():
    document = "a,b\n1,2\n"
    assert scan(document) == ["a,b\n", "1,2\n"]


@pytest.mark.parametrize(
    ("document", "char_index", "column_index", "line_index"),
    [
        # Header is line 0. "a,b\n" is 4 characters, so the second line's second field starts at 6.
        ("a,b\n1,123456789\n", 6 + 9, 1, 1),
        # First column of the first data row: starts right after the header.
        ("a,b\n123456789,2\n", 4 + 9, 0, 1),
        # Second data row, so the offset carries the first row's length too.
        ("a,b\n1,2\n3,123456789\n", 10 + 9, 1, 2),
    ],
)
def test_the_offsets_follow_the_measured_formula(document, char_index, column_index, line_index):
    with pytest.raises(ColumnTooLong) as raised:
        scan(document)
    assert (raised.value.char_index, raised.value.column_index, raised.value.line_index) == (
        char_index,
        column_index,
        line_index,
    )


def test_the_parsed_content_is_the_field_up_to_the_cap():
    with pytest.raises(ColumnTooLong) as raised:
        scan("a,b\n1,123456789\n")
    assert raised.value.content == "12345678"
    assert len(raised.value.content) == 8


def test_a_field_exactly_at_the_cap_is_accepted():
    """The cap is a maximum, not a limit one below: upstream reports a parsed length of cap + 1."""
    assert scan("a,b\n1,12345678\n") == ["a,b\n", "1,12345678\n"]


def test_an_unlimited_cap_never_fires():
    """areas.txt sets maxCharsPerColumn = -1 for the experimental wkt column. Measured on a feed
    whose areas.txt carries a 5,000-character area_name, which the jar accepts."""
    assert scan("a,b\n1," + "X" * 5000 + "\n", cap=UNLIMITED)[1].endswith("X\n")


def test_a_quoted_field_accumulates_across_lines():
    """A quoted field spanning lines is one field, so the cap applies to the whole of it. The
    scanner stays in its careful mode while a quote is open rather than trusting line length.
    """
    with pytest.raises(ColumnTooLong):
        scan('a,b\n1,"12345\n6789"\n')


def test_the_notice_carries_the_context_the_jar_reports():
    with pytest.raises(ColumnTooLong) as raised:
        scan("a,b\n1,123456789\n")
    context = raised.value.notice("stops.txt", 8).context
    assert sorted(context) == [
        "charIndex",
        "columnIndex",
        "filename",
        "lineIndex",
        "message",
        "parsedContent",
    ]
    assert context["filename"] == "stops.txt"
    # The message is ours, a deliberate and measured difference.
    assert context["message"].startswith("Length of parsed input (9) exceeds")


def test_the_cap_counts_utf16_units_not_characters():
    """2,049 astral characters are 4,098 UTF-16 units and overflow a 4,096 cap.

    Measured: the jar reports the failure with 2,048 characters of parsedContent, 4,096 units.
    Counting code points accepted the field outright. This is the fifth defect in this project
    from counting characters where Java counts units.
    """
    emoji = "\U0001f600"
    with pytest.raises(ColumnTooLong) as raised:
        scan("a,b\n1," + emoji * 5 + "\n", cap=8)
    assert raised.value.content == emoji * 4
    assert sum(2 if ord(c) > 0xFFFF else 1 for c in raised.value.content) == 8


def test_a_quote_is_not_content():
    """The opening quote advances the offset without counting toward the field, so a quoted field
    overflows one character later than the same unquoted text. Measured against the jar."""
    unquoted = pytest.raises(ColumnTooLong)
    with unquoted as bare:
        scan("a,b\n1,123456789\n", cap=8)
    with pytest.raises(ColumnTooLong) as quoted:
        scan('a,b\n1,"123456789"\n', cap=8)
    assert quoted.value.char_index == bare.value.char_index + 1


def test_a_doubled_quote_is_one_character_that_consumes_two():
    """Measured on a field of A, then "", then B: the jar's parsedContent holds a single quote and
    its charIndex is one further on than the same field without the escape."""
    with pytest.raises(ColumnTooLong) as raised:
        scan('a,b\n1,"AAA""BBBBB"\n', cap=8)
    assert raised.value.content == 'AAA"BBBB'
    assert raised.value.content.count('"') == 1


def test_a_quoted_field_spanning_lines_counts_both_halves():
    """The line index follows the physical line where parsing stopped, not where the row began.

    Measured on 3,000 characters, a newline, then 1,096 more: the jar reports lineIndex 2. An
    earlier fast path forwarded the short opening line without counting it, so the field read as
    1,096 characters and passed the cap.
    """
    with pytest.raises(ColumnTooLong) as raised:
        scan('a,b\n1,"AAA\nBBBBBB"\n', cap=8)
    assert raised.value.line_index == 2
    # The newline inside the quotes is content, which is what makes this one field.
    assert "\n" in raised.value.content


def test_an_over_long_header_cell_is_a_parse_failure_at_line_zero():
    """The header goes through the same scan: measured charIndex 4097, columnIndex 0, lineIndex 0
    for a 4,097-character header cell. Reading the header outside the guard crashed the loader
    instead of reporting the notice."""
    with pytest.raises(ColumnTooLong) as raised:
        scan("123456789,b\n1,2\n", cap=8)
    assert (raised.value.char_index, raised.value.column_index, raised.value.line_index) == (
        9,
        0,
        0,
    )


def test_a_long_header_cell_under_the_cap_reads_as_empty():
    """Univocity exposes a header cell longer than 1,024 characters as empty, so a 4,096-character
    header draws empty_column_name from the jar rather than unknown_column."""
    from gtfs_validator.columncap import MAX_HEADER_CHARS, truncate_header

    assert truncate_header(["ok", "X" * MAX_HEADER_CHARS]) == ["ok", "X" * MAX_HEADER_CHARS]
    assert truncate_header(["ok", "X" * (MAX_HEADER_CHARS + 1)]) == ["ok", ""]


def test_a_stray_quote_in_an_unquoted_field_is_not_a_quoted_field():
    """A quote only opens a field when it starts one.

    Toggling on every quote made `A"` open a phantom quoted field, and the scanner then swallowed
    the rest of the file: an over-long field after it went unreported, and a downstream rule
    reported a stop the jar never reaches. Measured with and without a trailing newline.
    """
    with pytest.raises(ColumnTooLong) as raised:
        scan('a,b\n1,A"XXXXXXXX\n', cap=8)
    assert raised.value.content == 'A"XXXXXX'
    assert raised.value.column_index == 1
