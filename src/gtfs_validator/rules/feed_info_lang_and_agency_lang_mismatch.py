"""MatchingFeedAndAgencyLangValidator: the feed's language against each agency's.

Three things this reports differently from `inconsistent_agency_lang`, which compares agencies with
each other, and all three are measured:

- It reports `toLanguageTag()`, the canonical spelling, so an agency declaring `en-US` against a feed
  declaring `en` is reported as `en-US` against `en`. The other rule reports `getLanguage()` and
  would say `en` against `en`.
- It is still `Locale.equals`, so that pair **is** a mismatch despite sharing a language.
- `mul` means multilingual and skips the check entirely, for every agency at once.

An agency with no language is skipped, and feed_info with no feed_lang stops the rule before any
agency is looked at.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared import locales
from gtfs_validator.rules._shared.agency_consistency import agencies
from gtfs_validator.rules.registry import file_rule

CODE = "feed_info_lang_and_agency_lang_mismatch"
FEED_INFO = "feed_info.txt"
# Locale.forLanguageTag("mul"): the ISO code for "multiple languages".
MULTILINGUAL = ("mul",)


@file_rule(code=CODE, severity=Severity.WARNING)
def check(feed, ctx: Context) -> Iterator[Notice]:
    feed_lang = next((row.get("feed_lang") for row in feed.rows(FEED_INFO)), None)
    if not feed_lang:
        return
    expected = locales.canonical(feed_lang)
    if expected == MULTILINGUAL:
        return
    for agency in agencies(feed):
        agency_lang = agency.get("agency_lang")
        if not agency_lang or locales.canonical(agency_lang) == expected:
            continue
        yield Notice(
            CODE,
            Severity.WARNING,
            {
                "csvRowNumber": agency["_row_number"],
                "agencyId": agency.get("agency_id") or "",
                "agencyName": agency.get("agency_name") or "",
                "agencyLang": locales.language_tag(agency_lang),
                "feedLang": locales.language_tag(feed_lang),
            },
        )
