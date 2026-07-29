"""Stage 2: stream a table's rows and report header and row-shape problems.

Row-drop semantics mirror upstream RowParser.checkRowLength: only an empty row
or a header/row length mismatch drops a row. Nothing else does.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator

from gtfs_validator.columncap import (
    DEFAULT_MAX_CHARS_PER_COLUMN,
    ColumnCapScanner,
    ColumnTooLong,
    truncate_header,
)
from gtfs_validator.csvquoting import (
    RowText,
    univocity_header,
    univocity_header_reverts,
    univocity_values,
)
from gtfs_validator.javatext import trim
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.table_status import TableLoad, TableStatus

MAX_ROW_NUMBER = 1_000_000_000

Row = dict[str, object]


def _check_header(
    filename: str,
    header: list[str],
    notices: NoticeContainer,
    required_columns: Iterable[str],
    recommended_columns: Iterable[str],
    known_columns: Iterable[str],
) -> None:
    # unknown_column compares against every column the schema declares, not
    # just the required and recommended ones. Plan 1 had no schema registry, so
    # it approximated with required|recommended and reported optional columns as
    # unknown whenever a caller passed lists at all.
    required = set(required_columns)
    recommended = set(recommended_columns)
    known = set(known_columns) or (required | recommended)

    seen: dict[str, int] = {}
    for position, name in enumerate(header):
        # DefaultTableHeaderValidator counts columns from zero and then reports
        # them from one: "Column indices are zero-based. We add 1 to make them
        # 1-based." Every index in these four notices is the reported form.
        index = position + 1
        if name == "":
            notices.add(
                Notice(
                    "empty_column_name",
                    Severity.ERROR,
                    {"filename": filename, "index": index},
                )
            )
            continue
        if name in seen:
            notices.add(
                Notice(
                    "duplicated_column",
                    Severity.ERROR,
                    {
                        "filename": filename,
                        "fieldName": name,
                        "firstIndex": seen[name],
                        "secondIndex": index,
                    },
                )
            )
        else:
            seen[name] = index
        # Upstream does not skip a duplicate here, so a column that is both
        # unknown and repeated draws one notice per position rather than one per
        # name. Emitting from the deduplicating map instead undercounts.
        if known and name not in known:
            notices.add(
                Notice(
                    "unknown_column",
                    Severity.INFO,
                    {"filename": filename, "fieldName": name, "index": index},
                )
            )

    for name in sorted(required - seen.keys()):
        notices.add(
            Notice(
                "missing_required_column",
                Severity.ERROR,
                {"filename": filename, "fieldName": name},
            )
        )
    for name in sorted(recommended - seen.keys()):
        notices.add(
            Notice(
                "missing_recommended_column",
                Severity.WARNING,
                {"filename": filename, "fieldName": name},
            )
        )


def _lines_in(text: str) -> int:
    """How many physical lines a row's source occupies.

    A row holding a quoted newline spans more than one, and the last line of a file need not be
    terminated, so the terminator count alone is short by one there.
    """
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _is_skipped_line(text: str) -> bool:
    """Whether univocity's skipEmptyLines drops this line before it is a row at all.

    A line with nothing left after trimming, which covers a blank one and a whitespace-only one.
    The exception is upstream's own: a whitespace line that ends the file *without* a terminator
    reaches the parser as a row of one empty column, and `empty_row` exists to describe it.
    """
    return not trim(text) and text.endswith(("\n", "\r"))


def parse_table(
    feed,
    filename: str,
    notices: NoticeContainer,
    required_columns: Iterable[str] = (),
    recommended_columns: Iterable[str] = (),
    known_columns: Iterable[str] = (),
    load: TableLoad | None = None,
    max_chars_per_column: int = DEFAULT_MAX_CHARS_PER_COLUMN,
) -> Iterator[Row]:
    load = load if load is not None else TableLoad()
    with feed.open_table(filename) as raw:
        # utf-8-sig strips a BOM if present; upstream tolerates one silently.
        #
        # errors="replace" rather than strict, matching CsvFile's decoder:
        # `.replaceWith("\uFFFD").onMalformedInput(CodingErrorAction.REPLACE)`.
        # That is what makes invalid_character reachable at all: the check looks
        # for U+FFFD, which only appears if malformed bytes are replaced rather
        # than raised on. Measured on a feed whose calendar.txt carries invalid
        # UTF-8: the jar parses it and reports invalid_row_length, while strict
        # decoding raised and dropped the whole table, taking
        # missing_calendar_and_calendar_date_files with it.
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        # Lines are scanned for the column cap on the way to the reader rather than after it:
        # the notice needs the character offset of the offending field, which csv.reader does
        # not expose. csv.reader takes any iterable of strings, so this changes nothing else.
        scanner = ColumnCapScanner(max_chars_per_column)
        source = RowText(scanner.scan(text))
        reader = csv.reader(source)
        # Rows are numbered by physical line, not by record. A row holding a quoted newline
        # occupies more than one line and upstream reports the *last* of them: measured on a
        # stops.txt whose second row spans lines 2 and 3, where the jar puts new_line_in_value at
        # 3 and the following row's invalid_row_length at 4. Counting records said 2 and 3.
        line_number = 0
        try:
            while True:
                raw_header = next(reader)
                header_text = source.take()
                line_number += _lines_in(header_text)
                if not _is_skipped_line(header_text):
                    break
                # skipEmptyLines applies to the header row too, so the header is the first line
                # with content on it. Taking a leading blank line as the header reported every
                # required column missing and never read the real one.
        except StopIteration:
            load.fail(TableStatus.EMPTY_FILE)
            return
        except ColumnTooLong as overflow:
            # The header is scanned like any other line: an over-long header cell is a parse
            # failure at lineIndex 0, and reading it outside this guard crashed the loader
            # instead of reporting the notice.
            notices.add(overflow.notice(filename, max_chars_per_column))
            load.fail(TableStatus.UNPARSABLE_ROWS)
            return
        # The revert applies before truncation: the scanner reads the raw row, and the literal
        # it hands back is what the cap would have measured.
        header = univocity_header(
            truncate_header(univocity_header_reverts(raw_header, header_text))
        )

        # Header notices are collected separately so their severity can be tested,
        # exactly as CsvFileLoader does: an ERROR here returns a container marked
        # INVALID_HEADERS and the rows are never scanned. Reading them anyway
        # would emit per-row notices upstream never produces.
        load.columns = frozenset(header)
        header_notices = NoticeContainer()
        _check_header(
            filename,
            header,
            header_notices,
            required_columns,
            recommended_columns,
            known_columns,
        )
        notices.merge(header_notices)
        if header_notices.has_errors():
            load.fail(TableStatus.INVALID_HEADERS)
            return

        rows = _capped(reader, filename, notices, load, max_chars_per_column)
        for raw_values in rows:
            row_text = source.take()
            # Advanced before any branch below, so a line the parser drops still costs its line
            # number: measured on a feed whose short row sits on line 5 behind a blank line and a
            # whitespace line, which the jar reports as row 5.
            line_number += _lines_in(row_text)
            row_number = line_number
            values = univocity_values(raw_values, row_text)
            if row_number > MAX_ROW_NUMBER:
                notices.add(
                    Notice(
                        "too_many_rows",
                        Severity.ERROR,
                        {"filename": filename, "rowNumber": row_number},
                    )
                )
                load.fail(TableStatus.UNPARSABLE_ROWS)
                return
            if len(values) == 0:
                continue
            if len(values) == 1 and values[0] == "":
                # A line of three spaces is not a row at all: univocity trims it to nothing and
                # skipEmptyLines drops it, so the jar reports nothing. What is left here is the
                # case upstream's own comment describes, a whitespace line ending the file
                # without a terminator, plus a lone `""`, which is not whitespace and so is never
                # dropped.
                if _is_skipped_line(row_text):
                    continue
                notices.add(
                    Notice(
                        "empty_row",
                        Severity.WARNING,
                        {"filename": filename, "csvRowNumber": row_number},
                    )
                )
                continue
            if len(values) != len(header):
                notices.add(
                    Notice(
                        "invalid_row_length",
                        Severity.ERROR,
                        {
                            "filename": filename,
                            "csvRowNumber": row_number,
                            "rowLength": len(values),
                            "headerCount": len(header),
                        },
                    )
                )
                load.fail(TableStatus.UNPARSABLE_ROWS)
                continue

            row: Row = {"_row_number": row_number}
            for field, value in zip(header, values, strict=False):
                if field == "":
                    continue
                # Value-level checks belong to stage 3, which sees the schema and
                # therefore applies them only to declared columns, as upstream does.
                row[field] = value
            yield row


def _capped(
    reader,
    filename: str,
    notices: NoticeContainer,
    load: TableLoad,
    cap: int,
) -> Iterator[list[str]]:
    """Yield rows until a column exceeds the cap, then report and stop.

    Upstream's parser throws a TextParsingException, which `CsvFileLoader` turns into
    `csv_parsing_failed` and a container with no entities, so the table ends there rather than
    skipping the row. Measured: the jar reports nothing else about stops.txt afterwards.
    """
    try:
        yield from reader
    except ColumnTooLong as overflow:
        notices.add(overflow.notice(filename, cap))
        load.fail(TableStatus.UNPARSABLE_ROWS)
