"""FeedContactValidator: feed_info needs a contact email or a contact URL.

The only rule in plan 3's cohort that treats whitespace as absence: it tests
isBlank() as well as presence, which the route and stop name rules deliberately
do not.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.javatext import is_blank
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import rule


def _blank(value: str | None) -> bool:
    # String.isBlank tests Character.isWhitespace, which excludes the
    # non-breaking space separators that str.isspace includes. See javatext.
    return value is None or is_blank(value)


@rule(
    code="missing_feed_contact_email_and_url",
    severity=Severity.WARNING,
    filename="feed_info.txt",
)
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    if _blank(row.get("feed_contact_email")) and _blank(row.get("feed_contact_url")):
        yield Notice(
            "missing_feed_contact_email_and_url",
            Severity.WARNING,
            {"csvRowNumber": row["_row_number"]},
        )
