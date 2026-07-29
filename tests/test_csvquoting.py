"""Which fields of a raw CSV row were quoted, which is what `csv.reader` throws away.

univocity skips whitespace around an *unquoted* field before any validator sees it and keeps
whatever is inside quotes, so the two cases are different values, different notices and different
presence. Python's reader treats them alike. Everything asserted here was measured on the jar;
the probe feeds are named below.
"""

import csv

from gtfs_validator.csvquoting import (
    FieldQuoting,
    RowText,
    field_quoting,
    univocity_header_reverts,
)

BARE = FieldQuoting(quoted=False, trailing_outside=0)


def REVERTED(value):
    return FieldQuoting(True, 0, value, reverted=True)


QUOTED = FieldQuoting(quoted=True, trailing_outside=0)


def test_plain_fields_are_all_unquoted():
    assert field_quoting("a,b,c") == [BARE, BARE, BARE]


def test_a_quoted_field_is_marked():
    assert field_quoting('a,"b",c') == [BARE, QUOTED, BARE]


def test_padding_around_an_unquoted_field_does_not_make_it_quoted():
    assert field_quoting("a, b ,c") == [BARE, BARE, BARE]


def test_whitespace_after_a_closing_quote_is_counted():
    # `csv.reader` appends those two spaces to the value and univocity discards them, so the
    # count is how many characters the caller has to drop back off.
    assert field_quoting('a,"b"  ,c') == [BARE, FieldQuoting(True, 2), BARE]


def test_a_tab_after_a_closing_quote_counts_too():
    assert field_quoting('a,"b"\t,c') == [BARE, FieldQuoting(True, 1), BARE]


def test_a_non_breaking_space_after_a_closing_quote_is_content_not_padding():
    # univocity's whitespace is code units at or below U+0020, the same set as String.trim, so
    # an NBSP after the closing quote is a stray character and the field reverts to literal.
    # Measured on probe `uq5`: the jar reports the value `"NBSP AFTER CLOSE TAIL"\u00a0`, outer
    # quotes kept and the NBSP surviving the right trim.
    assert field_quoting('a,"b"\u00a0,c') == [BARE, REVERTED('"b"\u00a0'), BARE]


def test_whitespace_before_the_opening_quote_still_means_quoted():
    # univocity skips it and then sees a quoted field. Python's reader does not, and hands the
    # quote characters back as content, so the scanner reads the field itself for this one case
    # and the caller prefers that reading. Measured: the jar reports a stop_name of ` " Spaced " `
    # as the value ` Spaced ` and names the same in leading_or_trailing_whitespaces.
    assert field_quoting('a, "b" ,c') == [BARE, FieldQuoting(True, 1, "b"), BARE]


def test_a_field_that_begins_with_its_quote_is_left_to_the_reader():
    # csv.reader already read it correctly, including across lines, so there is nothing to say.
    assert field_quoting('a,"b",c') == [BARE, FieldQuoting(True, 0, None), BARE]


def test_a_doubled_quote_is_unescaped_when_the_scanner_has_to_read_the_field():
    assert field_quoting('a, "say ""hi""" ,b')[1] == FieldQuoting(True, 1, 'say "hi"')


def test_an_unterminated_quote_after_whitespace_reads_to_the_end():
    assert field_quoting('a, "b') == [BARE, FieldQuoting(True, 0, "b")]


def test_a_delimiter_inside_quotes_does_not_start_a_field():
    assert field_quoting('a,"b,c",d') == [BARE, QUOTED, BARE]


def test_a_doubled_quote_does_not_close_the_field():
    assert field_quoting('a,"say ""hi""",b') == [BARE, QUOTED, BARE]


def test_a_newline_inside_quotes_does_not_end_the_row():
    assert field_quoting('a,"two\nlines",b') == [BARE, QUOTED, BARE]


def test_a_newline_outside_quotes_ends_the_row():
    assert field_quoting("a,b\nc,d") == [BARE, BARE]


def test_a_carriage_return_ends_the_row_too():
    assert field_quoting("a,b\r\n") == [BARE, BARE]


def test_a_trailing_delimiter_leaves_one_more_empty_field():
    assert field_quoting("a,b,") == [BARE, BARE, BARE]


def test_a_leading_delimiter_leaves_one_empty_field_first():
    assert field_quoting(",a") == [BARE, BARE]


def test_an_empty_row_has_no_fields():
    assert field_quoting("") == []
    assert field_quoting("\n") == []


def test_a_row_of_only_whitespace_is_one_unquoted_field():
    # It reaches `csv.reader` as one field, which is what makes empty_row reachable at all.
    assert field_quoting("   ") == [BARE]


def test_a_lone_quoted_empty_field_is_quoted():
    assert field_quoting('""') == [QUOTED]


def test_an_unterminated_quote_runs_to_the_end_of_the_text():
    assert field_quoting('a,"b') == [BARE, QUOTED]


# univocity's unescaped-quote handling, the default STOP_AT_DELIMITER: a lone quote followed by
# anything but optional whitespace and a delimiter or row end reverts the whole field to literal
# content, opening quote included: `"` + content parsed so far (escape pairs already collapsed)
# + `"` + the rest verbatim up to the next delimiter or row end, then right-trimmed. Measured on
# the `uq*` probes against the v8.0.1 jar and on the four feeds attached to upstream issue #1924;
# the difference is deliberate and measured.


def test_an_unescaped_quote_reverts_the_field_to_literal():
    # `"INNER QUOTE FR. "IL GIGANTE" (END)"` came back verbatim, outer quotes and all.
    assert field_quoting('a,"b "c" d",e')[1] == REVERTED('"b "c" d"')


def test_content_after_a_closing_quote_reverts_too():
    assert field_quoting('a,"b"x,c')[1] == REVERTED('"b"x')


def test_escape_pairs_collapse_before_the_revert_and_stay_raw_after():
    # `"DOUBLED ""Q"" THEN"X TAIL"` -> `"DOUBLED "Q" THEN"X TAIL"`: the pairs before the
    # unescaped quote read as one quote each, everything after it is untouched.
    assert field_quoting('a,"say ""hi"" b"x tail"')[1] == REVERTED('"say "hi" b"x tail"')


def test_whitespace_after_the_closing_quote_then_content_reverts_with_the_whitespace():
    # `"AFTER CLOSE" X TAIL` -> `"AFTER CLOSE" X TAIL`: the gap is not trailing padding once
    # something follows it.
    assert field_quoting('a,"b" x tail,c')[1] == REVERTED('"b" x tail')


def test_a_reverted_field_drops_whitespace_before_its_opening_quote():
    # univocity skips leading whitespace before deciding the field is quoted, so the literal
    # starts at the quote: ` "LEADING WS QUOTED "X" TAIL"` -> `"LEADING WS QUOTED "X" TAIL"`.
    assert field_quoting('a, "b "x tail,c')[1] == REVERTED('"b "x tail')


def test_a_reverted_field_is_trimmed_on_the_right():
    # `"NAKED TRAIL "X TAIL   ,` -> `"NAKED TRAIL "X TAIL`.
    assert field_quoting('a,"b "x tail   ,c')[1] == REVERTED('"b "x tail')


def test_whitespace_inside_a_reverted_field_before_a_final_quote_survives():
    # `"REST ENDS SPACY "X TAIL   "` kept all three spaces: only the very tail is trimmed.
    assert field_quoting('a,"b "x   ",c')[1] == REVERTED('"b "x   "')


def test_a_delimiter_ends_a_reverted_field():
    # univocity stops at the delimiter, so the row grows a field: measured as
    # invalid_row_length with rowLength 5 against a 4-column header on probe `uq2`.
    assert field_quoting('a,"b "x, c"') == [BARE, REVERTED('"b "x'), BARE]


def test_a_row_end_ends_a_reverted_field():
    assert field_quoting('a,"b "x\nnext,row') == [BARE, REVERTED('"b "x')]


def test_a_doubled_quote_at_the_field_start_is_still_an_escape():
    # `"""DOUBLED OPEN X TAIL"` -> `"DOUBLED OPEN X TAIL`: a clean close, no revert.
    assert field_quoting('a,"""b x"') == [BARE, QUOTED]


def test_the_header_honours_the_revert():
    # Measured on probe `uq6`: a stops.txt header cell of `"stop_i"d` draws unknown_column for
    # the literal `"stop_i"d` and missing_required_column for stop_id, where csv.reader would
    # have quietly read `stop_id`.
    text = '"stop_i"d,stop_name\n'
    names = next(csv.reader([text]))
    assert univocity_header_reverts(names, text) == ['"stop_i"d', "stop_name"]


def test_the_header_does_not_honour_the_whitespace_before_quote_override():
    # Measured on probe `uq8`: a header cell of ` "stop_name" ` stays the literal
    # `"stop_name"` on the jar's side, which is what the raw reader name gives after
    # univocity_header's trim, so the override must not fire here.
    text = 'stop_id, "stop_name" ,stop_lat\n'
    names = next(csv.reader([text]))
    assert univocity_header_reverts(names, text) == names


# RowText rests on one guarantee: `csv.reader` pulls lines from its iterator only until the row
# it is building is complete, so whatever arrived since the last row is exactly that row's
# source. It holds today in every shape, and it is an implementation property of CPython's C
# reader rather than a documented one, so it is asserted rather than assumed.

READER_SHAPES = [
    (["a,b\n", "1,2\n", "3,4\n"], [["a,b\n"], ["1,2\n"], ["3,4\n"]]),
    (["a,b\n", '1,"two\n', 'lines"\n'], [["a,b\n"], ['1,"two\n', 'lines"\n']]),
    (["a,b\n", "\n", "1,2\n"], [["a,b\n"], ["\n"], ["1,2\n"]]),
    (["a,b\r\n", "1,2\r\n"], [["a,b\r\n"], ["1,2\r\n"]]),
    (["a,b\n", "1,2"], [["a,b\n"], ["1,2"]]),
]


def test_row_text_hands_back_exactly_the_lines_of_each_row():
    for lines, expected in READER_SHAPES:
        source = RowText(lines)
        reader = csv.reader(source)
        taken = []
        for _ in reader:
            taken.append(source.take())
        assert taken == ["".join(group) for group in expected], lines


def test_row_text_is_empty_once_drained():
    source = RowText(["a,b\n"])
    reader = csv.reader(source)
    next(reader)
    assert source.take() == "a,b\n"
    assert source.take() == ""
