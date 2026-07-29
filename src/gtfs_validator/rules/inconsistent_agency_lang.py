"""AgencyConsistencyValidator: every agency should declare the same language.

The comparison is `Locale.equals` and the report is `Locale.getLanguage()`, which do
not agree about how much of the tag matters. See `_shared/locales.py`: `en-US`
against `en` is a mismatch reported as `en` against `en`.

Unlike the timezone branch this runs at any agency count, matching upstream, though a
single agency can never mismatch.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import locales
from gtfs_validator.rules._shared.agency_consistency import agencies
from gtfs_validator.rules.registry import file_rule


@file_rule(code="inconsistent_agency_lang", severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    expected: str | None = None
    expected_key: tuple[str, ...] = ()
    for agency in agencies(feed):
        lang = agency.get("agency_lang")
        if not lang:
            continue
        key = locales.canonical(lang)
        if expected is None:
            expected, expected_key = lang, key
            continue
        if key == expected_key:
            continue
        yield Notice(
            "inconsistent_agency_lang",
            Severity.WARNING,
            {
                "csvRowNumber": agency["_row_number"],
                "expected": locales.language_of(expected),
                "actual": locales.language_of(lang),
            },
        )
