"""Which fields of a raw CSV row univocity would treat as quoted.

`csv.reader` parses a row and throws this away, and upstream's parser settings make the
distinction load-bearing. `CsvFile.createDefaultParserSettings` disables univocity's trimming
*inside* quotes only, so the defaults still apply outside them: whitespace around an unquoted
field is skipped before any validator sees it, while whitespace inside quotes survives to
`DefaultFieldValidator.validateField`, which reports `leading_or_trailing_whitespaces` and trims.

The consequences are not confined to that one notice. A cell of a single space is *absent* when
bare and *present and empty* when quoted, so every rule asking whether a field was set inherits
the difference, which cascaded into three other checks before it was fixed.

This scanner answers the questions the reader cannot: per field, was it quoted, how many
whitespace characters sat between its closing quote and the delimiter, and whether an unescaped
quote reverted the field to literal content, which is univocity's default STOP_AT_DELIMITER
handling (the whole raw field survives, opening quote included; see known-divergences entry 10).
The values themselves otherwise still come from `csv.reader`, which stays the one authority on
where a row ends: a quoted field may span lines, and reproducing that is the part worth not
rewriting.

One case is beyond repair here. univocity skips whitespace *before* an opening quote and then
sees a quoted field, where `csv.reader` sees a literal one; `, "x" ,` therefore parses to
different values on the two sides, and to a different field count when the quotes hold a comma.
This scanner reports univocity's answer for it, which is honest about the intent, but the caller
cannot act on it without replacing the reader outright.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import NamedTuple

from gtfs_validator.javatext import TRIM_CEILING, trim

DELIMITER = ","
QUOTE = '"'
# A row ends at an unquoted line terminator. Both are at or below TRIM_CEILING, so the
# whitespace skips have to exclude them explicitly or they would swallow the end of the row.
ROW_END = "\r\n"


class FieldQuoting(NamedTuple):
    """One field's answer.

    `trailing_outside` counts whitespace after the closing quote, which `csv.reader` appends to
    the value and univocity discards. It is zero for an unquoted field, whose padding the caller
    trims wholesale instead.

    `value` is this scanner's own reading of the field, which the caller should prefer when
    present. It is set in two cases where `csv.reader`'s reading does not match the jar: when
    whitespace precedes the opening quote (univocity skips it and sees a quoted field, Python
    hands back the quote characters as content) and when an unescaped quote reverts the field
    to literal content. `reverted` distinguishes the second case, because the header row honours
    only that one: a whitespace-preceded quoted header cell stays literal on the jar's side too.
    """

    quoted: bool
    trailing_outside: int
    value: str | None = None
    reverted: bool = False


def field_quoting(text: str) -> list[FieldQuoting]:
    """One entry per field in `text`, which is the raw source of a single row."""
    if not text or text[0] in ROW_END:
        # csv.reader yields no fields for a blank line, so there is nothing to line up with.
        return []
    fields: list[FieldQuoting] = []
    index = 0
    end = len(text)
    while True:
        start = index
        index = _past_whitespace(text, index)
        quoted = index < end and text[index] == QUOTE
        value = None
        trailing = 0
        reverted = False
        if quoted:
            closed_at, content = _past_quoted_field(text, index + 1)
            index = _past_field(text, closed_at)
            if _all_whitespace(text, closed_at, index):
                trailing = index - closed_at
                if closed_at > start + 1 and text[start] != QUOTE:
                    # The field did not begin with its quote, so csv.reader read the quotes
                    # as content. This scanner's reading is the one that matches the jar.
                    value = content
            else:
                # An unescaped quote: something other than padding follows the quote that
                # would have closed the field. univocity's default STOP_AT_DELIMITER reverts
                # the whole field to literal content, opening quote included: escape pairs
                # before the unescaped quote are already collapsed, the rest rides along
                # verbatim to the delimiter or row end, and the tail is trimmed like any
                # unquoted field's. Measured on the `uq*` probes; see known-divergences
                # entry 10 for the shapes where csv.reader disagrees about the row itself.
                value = _rtrim(QUOTE + content + QUOTE + text[closed_at:index])
                reverted = True
        else:
            index = _past_field(text, index)
        fields.append(FieldQuoting(quoted, trailing, value, reverted))
        if index >= end or text[index] in ROW_END:
            return fields
        index += 1


def _past_whitespace(text: str, index: int) -> int:
    """Skip what univocity's ignoreLeadingWhitespaces skips before a field begins."""
    end = len(text)
    while index < end and text[index] <= TRIM_CEILING and text[index] not in ROW_END:
        index += 1
    return index


def _past_quoted_field(text: str, index: int) -> tuple[int, str]:
    """Index just past the closing quote, and the content between the quotes.

    A doubled quote is an escaped one: it does not close the field and it reads as one quote.
    An unterminated quote runs to the end of the text, which is what `csv.reader` does with it
    too. `index` arrives pointing at the first character *after* the opening quote.
    """
    end = len(text)
    content: list[str] = []
    while index < end:
        if text[index] != QUOTE:
            content.append(text[index])
            index += 1
        elif index + 1 < end and text[index + 1] == QUOTE:
            content.append(QUOTE)
            index += 2
        else:
            return index + 1, "".join(content)
    return end, "".join(content)


def _past_field(text: str, index: int) -> int:
    """Index of the delimiter or line terminator that ends this field."""
    end = len(text)
    while index < end and text[index] != DELIMITER and text[index] not in ROW_END:
        index += 1
    return index


def _all_whitespace(text: str, start: int, stop: int) -> bool:
    """Whether the gap between a closing quote and the delimiter is only padding.

    Padding closes the field cleanly and is discarded; anything else means the quote did not
    close the field at all and the whole field reverts to literal content.
    """
    return all(text[i] <= TRIM_CEILING for i in range(start, stop))


def _rtrim(value: str) -> str:
    """Drop trailing whitespace, by the same rule `javatext.trim` uses on both ends."""
    end = len(value)
    while end > 0 and value[end - 1] <= TRIM_CEILING:
        end -= 1
    return value[:end]


class RowText:
    """The source lines `csv.reader` consumed for the row it has just produced.

    The reader pulls from its iterator only until a row is complete, so everything that arrived
    since the last row is that row's raw text, line terminators included. `csvquoting` needs it:
    the parsed values no longer say which fields were quoted, and upstream's parser treats the
    two cases as different values with different presence.
    """

    def __init__(self, lines: Iterable[str]) -> None:
        self._lines = lines
        self._pending: list[str] = []

    def __iter__(self) -> Iterator[str]:
        for line in self._lines:
            self._pending.append(line)
            yield line

    def take(self) -> str:
        text = "".join(self._pending)
        self._pending.clear()
        return text


def univocity_values(values: list[str], text: str) -> list[str]:
    """Apply the trimming upstream's parser did before any validator saw the row.

    An unquoted field loses its padding outright and silently, which is why the jar reports no
    `leading_or_trailing_whitespaces` for `1, Acme ,...`. A quoted field keeps everything inside
    the quotes and loses only what followed the closing one, which `csv.reader` appends to the
    value; stage 3 is what trims that and reports the notice.

    When the scanner and the reader disagree about how many fields the row has, every field is
    treated as unquoted rather than lined up by index: a misaligned quoting flag would attribute
    one field's answer to another, and trimming is what the reader does with such a row today.
    The disagreement has one cause, documented in `csvquoting` and in known-divergences entry 1.
    """
    if QUOTE not in text:
        # Nothing to scan for: with no quote in the row every field is unquoted, which is what
        # the scanner would spend a character-by-character pass concluding. Real feeds are almost
        # entirely such rows, and the check is a C-level substring search against a Python loop.
        return [trim(value) for value in values]
    quoting = field_quoting(text)
    if len(quoting) != len(values):
        return [trim(value) for value in values]
    return [_resolved(value, field) for value, field in zip(values, quoting, strict=True)]


def _resolved(value: str, field: FieldQuoting) -> str:
    if not field.quoted:
        return trim(value)
    if field.value is not None:
        return field.value
    return value[: len(value) - field.trailing_outside] if field.trailing_outside else value


def univocity_header_reverts(names: list[str], text: str) -> list[str]:
    """Apply only the unescaped-quote revert to the header row's names.

    The header honours the revert like any data row: a stops.txt header cell of `"stop_i"d`
    draws `unknown_column` for the literal `"stop_i"d` and `missing_required_column` for
    `stop_id` (probe `uq6`). It does *not* honour the whitespace-before-quote override: the jar
    reports a header cell of ` "stop_name" ` as the unknown literal `"stop_name"` (probe `uq8`),
    which is exactly what `csv.reader`'s raw name gives after `univocity_header`'s trim, so
    those cells pass through untouched. Count misalignment falls back to the raw names, as
    `univocity_values` does for data rows.
    """
    if QUOTE not in text:
        return names
    quoting = field_quoting(text)
    if len(quoting) != len(names):
        return names
    return [
        field.value if field.reverted and field.value is not None else name
        for name, field in zip(names, quoting, strict=True)
    ]


def univocity_header(names: list[str]) -> list[str]:
    """Column names as the parser hands them over: trimmed, unless trimming would merge two.

    The header row is parsed like any other, so its padding goes the same way. The exception is
    measured rather than guessed: on a header of `stop_id,stop_name,stop_lat,stop_lon,
    <space>stop_name<space>` the jar reports `unknown_column` for the padded name *with* its
    spaces and no `duplicated_column`, while two identically padded names are trimmed and do
    collide. Trimming is skipped exactly when it would leave fewer distinct names than the file
    carried, and quoting makes no difference to it.
    """
    trimmed = [trim(name) for name in names]
    # Counted over the names that survive trimming. An empty column name is not a name being
    # merged with another: `a,,<space>` is two empty names to the jar, which reports
    # empty_column_name twice, where counting them made the header fall back to raw and turned
    # the second into an unknown_column of " ".
    return names if _distinct(trimmed) < _distinct(names) else trimmed


def _distinct(names: list[str]) -> int:
    return len({name for name in names if trim(name)})
