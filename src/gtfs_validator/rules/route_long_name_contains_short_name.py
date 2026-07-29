"""RouteNameValidator, third branch: a long name that merely repeats the short one.

The prefix test is case-insensitive, and the remainder after the prefix must be
empty or match "^\\s?[\\s\\-\\(\\)].*". That pattern reads as though a separator
were required after at most one space, but the \\s? is optional, so a remainder
beginning with a single space already satisfies the class itself. Measured: the
jar reports "N x Judah" against short name "N", which the stricter reading would
not. Only a remainder starting with a non-separator, such as "Judah" in
"NJudah", escapes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule

# Java's String.matches anchors at *both* ends, so the trailing ".*" has to
# consume the whole remainder, and Java's "." excludes five line terminators
# without DOTALL. Both details matter and an earlier reading of them was
# backwards: re.match leaves the tail unanchored, so ".*" always succeeded and
# re.DOTALL changed nothing. fullmatch plus an explicit class is the port.
#
# Only carriage return and line feed draw new_line_in_value, and that notice is
# an ERROR so the row never reaches a rule. The other three terminators pass
# field validation untouched and do reach it. Measured: a long name of "N", a
# space, a line separator and "X" is reported by us and not by the jar, and the
# same holds for the next line and paragraph separator characters.
_LINE_TERMINATORS = "\n\r\u0085\u2028\u2029"
# re.ASCII because Java's \s is ASCII-only unless UNICODE_CHARACTER_CLASS is
# set, which upstream does not set. Measured: a long name of "N", a no-break
# space and "Judah" is reported by us and not by the jar without this, because
# Python's \s matches the no-break space and Java's does not.
_SEPARATOR_RE = re.compile(rf"\s?[\s\-()][^{_LINE_TERMINATORS}]*", re.ASCII)


@rule(
    code="route_long_name_contains_short_name",
    severity=Severity.WARNING,
    filename="routes.txt",
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    short_name = row.get("route_short_name")
    long_name = row.get("route_long_name")
    if short_name is None or long_name is None:
        return
    if not long_name.lower().startswith(short_name.lower()):
        return
    remainder = long_name[len(short_name) :]
    if remainder and not _SEPARATOR_RE.fullmatch(remainder):
        return
    yield Notice(
        "route_long_name_contains_short_name",
        Severity.WARNING,
        {
            "routeId": row["route_id"],
            "csvRowNumber": row["_row_number"],
            "routeShortName": short_name,
            "routeLongName": long_name,
        },
    )
