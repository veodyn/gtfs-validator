"""Univocity's per-column character cap, and the offsets its exception reports.

`CsvParserSettings.setMaxCharsPerColumn` defaults to 4,096 and `areas.txt` overrides it to
unlimited, because a WKT polygon in the experimental `wkt` column can be far longer. Exceeding it
throws a `TextParsingException`, which becomes `csv_parsing_failed` and leaves the table with no
entities.

Six probes pin the semantics, and the first version of this file got four of them wrong:

| Probe | charIndex | line | parsedContent |
|---|---|---|---|
| 4,097-character header cell | 4097 | 0 | 4,096 characters |
| 4,097 characters unquoted | field start + 4097 | 1 | 4,096 characters |
| 4,097 characters quoted | one *more*, the opening quote is not content | 1 | 4,096 characters |
| quoted, split across two lines | 4137 | **2** | both halves, newline included |
| quoted with a doubled `""` | one more again | 1 | one quote, not two |
| 2,049 astral characters | 4136 | 1 | **2,048** characters |

So four rules, none of which a plain reading suggests:

- **The cap counts UTF-16 units, not characters.** 2,049 emoji are 4,098 units and overflow a
  4,096 cap while being only 2,049 Python characters. This is the fifth defect in this project
  from counting code points where Java counts units, and there is a standing note about it.
- **`charIndex` is the overflowing character's offset plus one**, in UTF-16 units. Expressing it
  as "field start + cap + 1" happens to be the same number for a plain unquoted field and is
  wrong for every other shape.
- **A quote is not content.** The opening quote advances the offset without counting, and a
  doubled `""` inside a quoted field is one content character, a single quote, that consumes two.
- **A newline inside a quoted field is content**, and the line index follows the physical line
  where parsing stopped rather than where the row began.

`message` is **not** reproduced: upstream's is 5.6 KB of univocity's own settings dump. See
a deliberate, measured difference from upstream's message text.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from gtfs_validator.javatext import utf16_length
from gtfs_validator.notices import Notice, Severity

DEFAULT_MAX_CHARS_PER_COLUMN = 4096
UNLIMITED = -1
# Univocity exposes a header cell longer than this as empty, which turns a long header into
# empty_column_name rather than unknown_column. Measured on a 4,096-character header cell.
MAX_HEADER_CHARS = 1024
_QUOTE = '"'
_DELIMITER = ","
_LINE_BREAKS = ("\r", "\n")


class ColumnTooLong(Exception):
    """One field over the cap, carrying what the notice needs."""

    def __init__(self, char_index: int, column_index: int, line_index: int, content: str) -> None:
        super().__init__(f"column {column_index} on line {line_index} exceeds the cap")
        self.char_index = char_index
        self.column_index = column_index
        self.line_index = line_index
        self.content = content

    def notice(self, filename: str, cap: int) -> Notice:
        return Notice(
            "csv_parsing_failed",
            Severity.ERROR,
            {
                "filename": filename,
                "charIndex": self.char_index,
                "columnIndex": self.column_index,
                "lineIndex": self.line_index,
                # Ours, not univocity's 5.6 KB settings dump. Divergence 10 records why.
                "message": (
                    f"Length of parsed input ({cap + 1}) exceeds the maximum number of "
                    f"characters defined in your parser settings ({cap})."
                ),
                "parsedContent": self.content,
            },
        )


class ColumnCapScanner:
    """Passes lines through to the CSV reader, watching field lengths as it goes.

    Cheap on ordinary input: a field cannot be longer than the line holding it, so a line whose
    own UTF-16 length is within the cap is forwarded after a length check. Only a long line, or
    one continuing a quoted field, is examined character by character.
    """

    def __init__(self, cap: int = DEFAULT_MAX_CHARS_PER_COLUMN) -> None:
        self.cap = cap
        self._offset = 0
        self._line_index = 0
        self._in_quotes = False
        # Field state is instance-level because a quoted field spans lines: resetting it per line
        # made a field split as "AAA\nBBB" read as two short fields and pass a cap it exceeds.
        self._column_index = 0
        self._length = 0
        self._content: list[str] = []

    def scan(self, lines: Iterable[str]) -> Iterator[str]:
        for line in lines:
            if self.cap != UNLIMITED and not self._skippable(line):
                self._examine(line)
            self._offset += utf16_length(line)
            self._line_index += 1
            yield line

    def _skippable(self, line: str) -> bool:
        """Whether this line can be forwarded without counting its characters.

        Three conditions, and the third is the one that was missing: a line containing *any* quote
        has to be examined, because a quote can open a field that continues onto the next line and
        the content before the newline still counts toward it. Tracking only the quote parity lost
        that content, so a field of 3,000 characters then 1,096 more read as one of 1,096 and
        passed a cap it exceeds.

        A feed that quotes most of its lines therefore pays the character scan on them. That is a
        larger constant on the same linear pass, and it buys the only accounting that matches.
        """
        return not self._in_quotes and _QUOTE not in line and utf16_length(line) <= self.cap

    def _start_field(self) -> None:
        self._length = 0
        self._content = []

    def _examine(self, line: str) -> None:
        if not self._in_quotes:
            self._column_index = 0
            self._start_field()
        offset = self._offset
        position = 0
        while position < len(line):
            character = line[position]
            width = utf16_length(character)
            if character == _QUOTE and (self._in_quotes or self._length == 0):
                # A quote only opens a field when it *starts* one. Toggling on every quote made a
                # stray quote inside an unquoted value open a phantom quoted field, and the
                # scanner then swallowed the rest of the file: an over-long field after `A"` was
                # not reported at all, and a downstream rule reported a stop the jar never
                # reaches. Measured.
                if self._in_quotes and line[position + 1 : position + 2] == _QUOTE:
                    # A doubled quote is one content character consuming two, which is why
                    # charIndex cannot be derived from the field's start.
                    self._take(_QUOTE, offset)
                    offset += 2
                    position += 2
                    continue
                self._in_quotes = not self._in_quotes
                offset += width
                position += 1
                continue
            if not self._in_quotes and character == _DELIMITER:
                self._column_index += 1
                self._start_field()
                offset += width
                position += 1
                continue
            if not self._in_quotes and character in _LINE_BREAKS:
                offset += width
                position += 1
                continue
            # Inside quotes a newline is content, which is what makes a split field one field.
            self._take(character, offset)
            offset += width
            position += 1

    def _take(self, character: str, offset: int) -> None:
        self._length += utf16_length(character)
        if self._length <= self.cap:
            self._content.append(character)
            return
        raise ColumnTooLong(
            offset + 1, self._column_index, self._line_index, "".join(self._content)
        )


def truncate_header(header: list[str]) -> list[str]:
    """Univocity exposes an over-long header cell as empty.

    Measured on a 4,096-character header cell, under the column cap and so not a parse failure:
    the jar reports `empty_column_name` and a missing required column, where keeping the text
    reported `unknown_column` instead.
    """
    return ["" if utf16_length(cell) > MAX_HEADER_CHARS else cell for cell in header]
