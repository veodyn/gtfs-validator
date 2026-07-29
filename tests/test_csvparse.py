import zipfile

from gtfs_validator.container import open_feed
from gtfs_validator.csvparse import parse_table
from gtfs_validator.notices import NoticeContainer


def feed_with(tmp_path, body):
    path = tmp_path / "feed.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("agency.txt", body)
    return open_feed(path)


def notice_codes(notices):
    return [n.code for group in notices.grouped().values() for n in group]


def notices_named(notices, code):
    return [n for g in notices.grouped().values() for n in g if n.code == code]


def test_rows_carry_source_row_numbers(tmp_path):
    feed = feed_with(tmp_path, "agency_id,agency_name\n1,Acme\n2,Beta\n")
    notices = NoticeContainer()
    rows = list(parse_table(feed, "agency.txt", notices))
    assert [r["_row_number"] for r in rows] == [2, 3]
    assert rows[0]["agency_name"] == "Acme"


def test_invalid_row_length_drops_the_row(tmp_path):
    feed = feed_with(tmp_path, "a,b\n1,2\n1,2,3\n")
    notices = NoticeContainer()
    rows = list(parse_table(feed, "agency.txt", notices))
    assert len(rows) == 1
    found = notices_named(notices, "invalid_row_length")[0]
    assert found.context == {
        "filename": "agency.txt",
        "csvRowNumber": 3,
        "rowLength": 3,
        "headerCount": 2,
    }


def test_empty_row_is_reported_and_dropped(tmp_path):
    # A lone `""`, not a line of spaces: univocity trims an unquoted line to nothing and its
    # skipEmptyLines drops it before any notice, which this test used to assert the opposite of.
    # See tests/test_csvparse_whitespace.py for all three shapes and what the jar says to each.
    feed = feed_with(tmp_path, 'a,b\n1,2\n""\n')
    notices = NoticeContainer()
    rows = list(parse_table(feed, "agency.txt", notices))
    assert len(rows) == 1
    assert "empty_row" in notice_codes(notices)


def test_duplicated_column_is_reported(tmp_path):
    feed = feed_with(tmp_path, "a,b,a\n1,2,3\n")
    notices = NoticeContainer()
    list(parse_table(feed, "agency.txt", notices))
    dup = notices_named(notices, "duplicated_column")
    assert dup[0].context == {
        "filename": "agency.txt",
        "fieldName": "a",
        "firstIndex": 1,
        "secondIndex": 3,
    }


def test_empty_column_name_is_reported(tmp_path):
    feed = feed_with(tmp_path, "a,,c\n1,2,3\n")
    notices = NoticeContainer()
    list(parse_table(feed, "agency.txt", notices))
    empty = notices_named(notices, "empty_column_name")
    assert empty[0].context == {"filename": "agency.txt", "index": 2}


def test_missing_required_and_recommended_columns(tmp_path):
    feed = feed_with(tmp_path, "a\n1\n")
    notices = NoticeContainer()
    list(
        parse_table(
            feed,
            "agency.txt",
            notices,
            required_columns=("b",),
            recommended_columns=("c",),
        )
    )
    codes = notice_codes(notices)
    assert "missing_required_column" in codes
    assert "missing_recommended_column" in codes


def test_unknown_column_is_info(tmp_path):
    feed = feed_with(tmp_path, "a,zzz\n1,2\n")
    notices = NoticeContainer()
    list(parse_table(feed, "agency.txt", notices, required_columns=("a",)))
    unknown = notices_named(notices, "unknown_column")
    assert unknown[0].context == {
        "filename": "agency.txt",
        "fieldName": "zzz",
        "index": 2,
    }


def test_value_level_checks_belong_to_the_typing_stage(tmp_path):
    # These two fired here in plan 1, for every column in the file. Upstream
    # emits them from DefaultFieldValidator, which runs only for columns the
    # schema declares, so they moved to typing_stage and must not fire here.
    # See tests/test_typing_stage.py for their coverage.
    feed = feed_with(tmp_path, 'a,b\n" x ","y\nz"\n')
    notices = NoticeContainer()
    rows = list(parse_table(feed, "agency.txt", notices))
    codes = notice_codes(notices)
    assert "leading_or_trailing_whitespaces" not in codes
    assert "new_line_in_value" not in codes
    # The raw value reaches stage 3 untouched, whitespace included.
    assert rows[0]["a"] == " x "


def test_header_indices_are_one_based(tmp_path):
    # DefaultTableHeaderValidator says so outright: "Column indices are
    # zero-based. We add 1 to make them 1-based." Measured against the jar on an
    # agency.txt header of "agency_id,zzz,agency_name,zzz,,agency_url,agency_id,
    # agency_timezone,": empty_column_name at 5 and 9, duplicated_column zzz at
    # 2/4 and agency_id at 1/7, unknown_column zzz at 2 and 4.
    feed = feed_with(tmp_path, "a,zzz,b,zzz,,c,a,d,\n1,2,3,4,5,6,7,8,9\n")
    notices = NoticeContainer()
    list(parse_table(feed, "agency.txt", notices, known_columns=("a", "b", "c", "d")))
    empty = [n.context["index"] for n in notices_named(notices, "empty_column_name")]
    assert empty == [5, 9]
    dup = [
        (n.context["fieldName"], n.context["firstIndex"], n.context["secondIndex"])
        for n in notices_named(notices, "duplicated_column")
    ]
    assert dup == [("zzz", 2, 4), ("a", 1, 7)]


def test_a_repeated_unknown_column_is_reported_once_per_occurrence(tmp_path):
    # The header loop emits unknown_column inside the per-column body without
    # skipping a duplicate, so a column that is both unknown and repeated draws
    # one notice per position. Reporting per distinct name undercounts: the jar
    # reports two for the header below and we reported one.
    feed = feed_with(tmp_path, "a,zzz,b,zzz\n1,2,3,4\n")
    notices = NoticeContainer()
    list(parse_table(feed, "agency.txt", notices, known_columns=("a", "b")))
    unknown = notices_named(notices, "unknown_column")
    assert [n.context["index"] for n in unknown] == [2, 4]


def test_malformed_bytes_are_replaced_rather_than_raised_on(tmp_path):
    # CsvFile decodes with .replaceWith("\ufffd").onMalformedInput(REPLACE), which
    # is what makes invalid_character reachable: the check looks for U+FFFD, and
    # strict decoding would raise before any cell was inspected. Measured on a
    # feed whose calendar.txt carries invalid UTF-8: the jar parses it and reports
    # invalid_row_length, where we raised and dropped the whole table.
    path = tmp_path / "feed"
    path.mkdir()
    (path / "agency.txt").write_bytes(b"agency_name,agency_url\nAcme\xff,https://x.test\n")
    feed = open_feed(path)
    notices = NoticeContainer()
    rows = list(parse_table(feed, "agency.txt", notices))
    assert len(rows) == 1
    assert "\ufffd" in rows[0]["agency_name"]
