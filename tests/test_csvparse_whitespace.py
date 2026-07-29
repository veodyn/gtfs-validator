"""Stage 2's half of univocity's whitespace handling, and the presence it decides.

The parser trims an unquoted field before anything looks at it and keeps whatever is inside
quotes, so one cell of a single space has two meanings: absent when bare, present and empty when
quoted. Stage 3 then reports `leading_or_trailing_whitespaces` for the quoted one only, because
the bare one arrives with nothing left to trim.

Every expectation was measured on the jar, closing the oldest recorded difference, which this
closes, and its three recorded cascades.
"""

import json
import zipfile

from gtfs_validator.cli import main
from gtfs_validator.container import open_feed
from gtfs_validator.csvparse import parse_table
from gtfs_validator.notices import NoticeContainer

STOPS = "stop_id,stop_name,stop_lat,stop_lon\nS1,One,40.10,-74.0\nS2,Two,40.20,-74.0\n"


def rows_of(tmp_path, body, name="agency.txt", known=()):
    path = tmp_path / "feed.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, body)
    notices = NoticeContainer()
    rows = list(parse_table(open_feed(path), name, notices, known_columns=known))
    return rows, notices


AGENCY_COLUMNS = ("agency_id", "agency_name")


def codes_in(notices):
    return [notice.code for group in notices.grouped().values() for notice in group]


def contexts_of(notices, code):
    return [n.context for g in notices.grouped().values() for n in g if n.code == code]


def test_padding_around_a_bare_field_is_gone_before_stage_three_sees_it(tmp_path):
    rows, _ = rows_of(tmp_path, "a,b\n1, Acme Transit \n")
    assert rows[0]["b"] == "Acme Transit"


def test_padding_inside_quotes_survives_the_parse(tmp_path):
    # Stage 3 is what trims it and reports the notice, so stage 2 has to hand it over intact.
    rows, _ = rows_of(tmp_path, 'a,b\n1," Acme Transit "\n')
    assert rows[0]["b"] == " Acme Transit "


def test_a_bare_whitespace_cell_arrives_empty(tmp_path):
    # Empty is how stage 3 learns the field is absent: `if not raw` stores None for it, which is
    # what upstream's null column value means. A present-but-blank value cascades instead, and
    # that cascade is what made us invent notices the jar does not emit.
    rows, _ = rows_of(tmp_path, "a,b\n1, \n")
    assert rows[0]["b"] == ""


def test_a_quoted_whitespace_cell_keeps_its_space(tmp_path):
    rows, _ = rows_of(tmp_path, 'a,b\n1," "\n')
    assert rows[0]["b"] == " "


def test_whitespace_after_a_closing_quote_is_not_part_of_the_value(tmp_path):
    rows, _ = rows_of(tmp_path, 'a,b\n1,"Acme"  \n')
    assert rows[0]["b"] == "Acme"


def test_a_bare_tab_padded_cell_is_trimmed(tmp_path):
    rows, _ = rows_of(tmp_path, "a,b\n1,\tAcme\t\n")
    assert rows[0]["b"] == "Acme"


def test_a_non_breaking_space_is_not_whitespace_here(tmp_path):
    # String.trim's ceiling is U+0020, so NBSP is content. Measured: the jar carries a stop_name
    # of NBSP-Nbsp-NBSP through to stopName intact and reports no whitespace notice for it.
    rows, _ = rows_of(tmp_path, "a,b\n1,\u00a0Nbsp\u00a0\n")
    assert rows[0]["b"] == "\u00a0Nbsp\u00a0"


def test_padded_column_names_are_trimmed(tmp_path):
    rows, notices = rows_of(
        tmp_path, " agency_id , agency_name \n1,Acme\n", known=AGENCY_COLUMNS
    )
    assert rows[0]["agency_name"] == "Acme"
    assert "unknown_column" not in codes_in(notices)


def test_a_padded_column_name_stays_raw_when_trimming_would_collapse_two(tmp_path):
    # univocity trims the header row like any other, but not when trimming would leave fewer
    # distinct names than the file carried: two columns must not become one. Measured on a
    # stops.txt header of `stop_id,stop_name,stop_lat,stop_lon, stop_name `, where the jar
    # reports unknown_column for " stop_name " with its spaces and no duplicated_column.
    _, notices = rows_of(
        tmp_path, "agency_id,agency_name, agency_name \n1,Acme,Acme\n", known=AGENCY_COLUMNS
    )
    unknown = contexts_of(notices, "unknown_column")
    assert [context["fieldName"] for context in unknown] == [" agency_name "]
    assert "duplicated_column" not in codes_in(notices)


def test_two_identically_padded_names_are_trimmed_and_collide(tmp_path):
    # Here trimming loses nothing: the raw names were already the same name twice, so the
    # duplicate is real. Measured on a header carrying `" extra "," extra "`.
    _, notices = rows_of(tmp_path, "agency_id, extra , extra \n1,x,y\n")
    duplicated = contexts_of(notices, "duplicated_column")
    assert [context["fieldName"] for context in duplicated] == ["extra"]


def test_a_whitespace_only_line_is_skipped_silently(tmp_path):
    # univocity trims the line to nothing and its skipEmptyLines drops it, so there is no row
    # and no notice. We reported empty_row for it, which is the `whitespace-line` probe.
    rows, notices = rows_of(tmp_path, "a,b\n1,2\n   \n")
    assert len(rows) == 1
    assert codes_in(notices) == []


def test_a_whitespace_only_last_line_without_a_newline_draws_empty_row(tmp_path):
    # Upstream's own comment on this: without the newline univocity reads it as one row of one
    # empty column, "(sic!)", and the notice exists to describe that.
    rows, notices = rows_of(tmp_path, "a,b\n1,2\n   ")
    assert len(rows) == 1
    assert contexts_of(notices, "empty_row") == [{"filename": "agency.txt", "csvRowNumber": 3}]


def test_a_lone_quoted_empty_field_draws_empty_row(tmp_path):
    rows, notices = rows_of(tmp_path, 'a,b\n1,2\n""\n')
    assert len(rows) == 1
    assert contexts_of(notices, "empty_row") == [{"filename": "agency.txt", "csvRowNumber": 3}]


def test_a_lone_quoted_whitespace_field_is_a_one_column_row(tmp_path):
    # It is not empty, so it is measured against the header instead. Measured on the `wsr` probe,
    # where the jar reports invalid_row_length with rowLength 1.
    rows, notices = rows_of(tmp_path, 'a,b\n1,2\n" "\n')
    assert len(rows) == 1
    assert contexts_of(notices, "invalid_row_length") == [
        {"filename": "agency.txt", "csvRowNumber": 3, "rowLength": 1, "headerCount": 2}
    ]


def test_a_quoted_field_spanning_lines_keeps_its_whitespace_and_its_row(tmp_path):
    # The row's raw source is more than one line, which is the case RowText exists to get right:
    # csv.reader assembles the row and the scanner reads the text it consumed doing so.
    rows, notices = rows_of(tmp_path, 'a,b\n1," two\nlines "\n')
    assert len(rows) == 1
    assert rows[0]["b"] == " two\nlines "
    assert codes_in(notices) == []


def test_a_quoted_field_spanning_lines_next_to_a_padded_one(tmp_path):
    # The multi-line field must not shift which field the padding belongs to.
    rows, _ = rows_of(tmp_path, 'a,b,c\n1," two\nlines ", padded \n')
    assert rows[0]["b"] == " two\nlines "
    assert rows[0]["c"] == "padded"


def test_a_quoted_comma_after_whitespace_splits_the_row_and_we_report_it(tmp_path):
    # The one case left open, asserted to pin what we do rather than to claim it matches.
    # univocity skips the space, sees a quoted field and reads one value of `x,y`; csv.reader
    # sees two literal fields, so the row is one field too long and we drop it. Measured on the
    # `wsplit` probe, whose stops.txt carries ` "Two, Three" `: the jar reports nothing at all.
    # Repairing it means replacing the reader, not consulting the scanner, because the two
    # disagree about the row's *shape*, which the reader cannot repair.
    rows, notices = rows_of(tmp_path, 'a,b,c\n1, "x,y" ,3\n')
    assert rows == []
    assert contexts_of(notices, "invalid_row_length") == [
        {"filename": "agency.txt", "csvRowNumber": 2, "rowLength": 4, "headerCount": 3}
    ]


def test_a_row_spanning_lines_is_numbered_by_its_last_line(tmp_path):
    # Upstream numbers by physical line, not by record: a row occupying lines 2 and 3 is row 3,
    # and the row after it is row 4. Measured on the `rv3` probe, where the jar puts
    # new_line_in_value at 3 and invalid_row_length at 4 while we said 2 and 3.
    rows, notices = rows_of(tmp_path, 'a,b,c\n1,"two\nlines",3\n4,5\n')
    assert [row["_row_number"] for row in rows] == [3]
    assert contexts_of(notices, "invalid_row_length") == [
        {"filename": "agency.txt", "csvRowNumber": 4, "rowLength": 2, "headerCount": 3}
    ]


def test_skipped_lines_still_advance_the_row_number(tmp_path):
    # A blank line and a whitespace line are dropped without a notice, and both still count.
    # Measured on the `num` probe: the short row on physical line 5 is reported as row 5.
    _, notices = rows_of(tmp_path, "a,b\n1,2\n\n   \n3\n")
    assert contexts_of(notices, "invalid_row_length") == [
        {"filename": "agency.txt", "csvRowNumber": 5, "rowLength": 1, "headerCount": 2}
    ]


def test_a_blank_line_before_the_header_is_skipped(tmp_path):
    # skipEmptyLines applies to the header row too, so the header is the first line with content
    # and the rows after it are numbered from where it actually sat. Measured on the `rv6` probe,
    # where we reported missing_required_column for a header we had not read yet.
    rows, notices = rows_of(tmp_path, "\n\na,b\n1,2\n", known=("a", "b"))
    assert [row["a"] for row in rows] == ["1"]
    assert [row["_row_number"] for row in rows] == [4]
    assert codes_in(notices) == []


def test_a_whitespace_line_before_the_header_is_skipped_too(tmp_path):
    rows, _ = rows_of(tmp_path, "   \na,b\n1,2\n", known=("a", "b"))
    assert [row["_row_number"] for row in rows] == [3]


def test_an_empty_column_name_does_not_hold_the_header_raw(tmp_path):
    # The collision rule counts only names that survive trimming: an empty name and a
    # whitespace-only one are the same column name, not two distinct ones being merged.
    # Measured on the `rv5` probe, where the jar reports empty_column_name twice and we reported
    # it once plus an unknown_column named " ".
    _, notices = rows_of(tmp_path, "a,b,, \n1,2,x,y\n", known=("a", "b"))
    assert [c["index"] for c in contexts_of(notices, "empty_column_name")] == [3, 4]
    assert "unknown_column" not in codes_in(notices)


def _feed(tmp_path, stops=STOPS, agency=None):
    path = tmp_path / "feed.zip"
    tables = {
        "agency.txt": agency
        or (
            "agency_id,agency_name,agency_url,agency_timezone\n"
            "1,Acme,https://example.com,America/New_York\n"
        ),
        "routes.txt": "route_id,agency_id,route_short_name,route_type\nR1,1,10,3\n",
        "trips.txt": "route_id,service_id,trip_id\nR1,WEEK,T1\n",
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\nT1,08:10:00,08:10:00,S2,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
            "start_date,end_date\nWEEK,1,1,1,1,1,0,0,20260101,20261231\n"
        ),
        "stops.txt": stops,
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in tables.items():
            archive.writestr(name, body)
    return path


def report_for(tmp_path, **kwargs):
    out = tmp_path / "out"
    main(["-i", str(_feed(tmp_path, **kwargs)), "-o", str(out), "-d", "2026-06-01"])
    return json.loads((out / "report.json").read_text())


def samples_of(report, code):
    for notice in report["notices"]:
        if notice["code"] == code:
            return notice["sampleNotices"]
    return []


def test_a_bare_padded_value_earns_no_whitespace_notice_end_to_end(tmp_path):
    padded = "stop_id,stop_name,stop_lat,stop_lon\nS1, One ,40.10,-74.0\nS2,Two,40.20,-74.0\n"
    report = report_for(tmp_path, stops=padded)
    assert samples_of(report, "leading_or_trailing_whitespaces") == []


def test_a_quoted_padded_value_earns_one(tmp_path):
    padded = 'stop_id,stop_name,stop_lat,stop_lon\nS1," One ",40.10,-74.0\nS2,Two,40.20,-74.0\n'
    report = report_for(tmp_path, stops=padded)
    assert samples_of(report, "leading_or_trailing_whitespaces") == [
        {
            "filename": "stops.txt",
            "csvRowNumber": 2,
            "fieldName": "stop_name",
            "fieldValue": " One ",
        }
    ]


def test_a_bare_whitespace_value_reads_as_a_missing_field(tmp_path):
    # The presence cascade, in the direction that used to invent a notice: stop_name is
    # conditionally required for a platform, and a bare space leaves it absent.
    blank = "stop_id,stop_name,stop_lat,stop_lon\nS1, ,40.10,-74.0\nS2,Two,40.20,-74.0\n"
    report = report_for(tmp_path, stops=blank)
    assert [sample["stopId"] for sample in samples_of(report, "missing_stop_name")] == ["S1"]
    assert samples_of(report, "leading_or_trailing_whitespaces") == []
