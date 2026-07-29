"""DuplicateFareMediaValidator: two fare media that are the same thing twice.

The key is (name, type), and `putIfAbsent` keeps the **first** row per key, so a
third copy names the first again rather than the second. Measured on a fare_media.txt
of A/B/C/D/E/F: A and B share a name and type and draw one notice; C shares the name
with a different type and draws none; D and E share a blank name and a type and draw
one, so a blank name groups rather than being skipped; and F, a third copy of A's
key, draws a notice naming A rather than B.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules.registry import file_rule


@file_rule(code="duplicate_fare_media", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    first: dict[tuple[str | None, int | None], dict] = {}
    for row in feed.rows("fare_media.txt"):
        key = (row.get("fare_media_name"), row.get("fare_media_type"))
        existing = first.setdefault(key, row)
        if existing is row:
            continue
        yield Notice(
            "duplicate_fare_media",
            Severity.WARNING,
            {
                "csvRowNumber1": existing["_row_number"],
                "fareMediaId1": existing.get("fare_media_id"),
                "csvRowNumber2": row["_row_number"],
                "fareMediaId2": row.get("fare_media_id"),
            },
        )
