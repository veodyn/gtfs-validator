"""Drift tests for the three generated files that had none.

`notice_schema.json`, `notice_descriptions.json` and `display_languages.json` are
produced by `tools/sync_notice_schema.py`, `sync_notice_descriptions.py` and
`sync_display_languages.py`, each of which runs the pinned jar or the JDK. Every
other generated file in `data/` is pinned by a test; these three were not, so a
regeneration that silently dropped half its output would have committed clean.

What a drift test can assert here, and what it cannot: it cannot re-derive the
values, because that needs the jar. It pins the *shape and the anchors* instead,
which is the same thing `tests/test_jts_messages.py` does. A regeneration that
changes a pinned value fails here, at the file, rather than inside a notice or an
HTML page where the cause is much further from the symptom.

The counts are anchors, not guesses. Each was read off the committed file, and the
point of writing it down is that the next regeneration has to agree with it or say
why.
"""

from __future__ import annotations

import json
from importlib.resources import files

import pytest

from gtfs_validator.manifest import IMPLEMENTED


def _data(name: str) -> dict:
    return json.loads(files("gtfs_validator.data").joinpath(name).read_text(encoding="utf-8"))


SCHEMA = _data("notice_schema.json")
DESCRIPTIONS = _data("notice_descriptions.json")
LANGUAGES = _data("display_languages.json")


# --- notice_schema.json: the jar's own --export_notices_schema output -------------


def test_the_schema_carries_every_notice_upstream_declares() -> None:
    """181, not 176.

    The 176 in the docs counts notice *classes*; this file is keyed by code and
    carries five more, so a test asserting 176 here would be asserting the wrong
    number confidently. Pinned at what the pinned jar exports.
    """
    assert len(SCHEMA) == 181


def test_every_implemented_code_has_a_schema_entry() -> None:
    """The join that matters: a code we emit with no schema entry renders an HTML
    report with a blank description, which no notice-level test would catch.
    """
    missing = sorted(code for code in IMPLEMENTED if code not in SCHEMA)
    assert missing == []


def test_every_entry_has_the_fields_that_are_always_present() -> None:
    """Written as `description` too at first, and 57 entries said otherwise.

    A top-level `description` is optional in upstream's export, and the HTML report
    does not read it: `_comment` reads `properties.<field>.description`, one level
    down. Asserting the field the name suggested would have pinned a rule the data
    does not follow.
    """
    required = {"code", "severityLevel", "type", "shortSummary", "properties"}
    incomplete = sorted(code for code, entry in SCHEMA.items() if not required <= set(entry))
    assert incomplete == []


def test_the_optional_fields_are_absent_exactly_where_they_were() -> None:
    """An anchor on the two optional fields rather than a rule about them.

    If a regeneration starts or stops emitting these, the count moves and this
    fails, which is the whole job: nothing else in the suite reads them, so the
    change would otherwise land silently.
    """
    without_description = sum(1 for entry in SCHEMA.values() if "description" not in entry)
    without_references = sum(1 for entry in SCHEMA.values() if "references" not in entry)
    assert (without_description, without_references) == (57, 29)


@pytest.mark.parametrize(
    ("code", "severity"),
    [
        ("attribution_without_role", "WARNING"),
        ("empty_file", "ERROR"),
        ("unknown_file", "INFO"),
    ],
)
def test_the_severity_of_an_anchor_code_is_unchanged(code: str, severity: str) -> None:
    """One code per severity. Severity is what sorts the report and colours the
    page, so a regeneration that moved one would change output everywhere.
    """
    assert SCHEMA[code]["severityLevel"] == severity


# --- notice_descriptions.json: rendered by the flexmark bundled in the jar --------


def test_the_descriptions_name_how_they_were_produced() -> None:
    """`_meta` is the provenance, and it is the field that tells a future reader
    which jar and which renderer produced the text below it.
    """
    assert DESCRIPTIONS["_meta"]["source"] == "gtfs-validator 8.0.1"
    assert "flexmark" in DESCRIPTIONS["_meta"]["method"]


def test_there_is_a_description_for_every_schema_entry() -> None:
    assert sorted(DESCRIPTIONS["descriptions"]) == sorted(SCHEMA)


def test_no_description_is_empty() -> None:
    """The generator writes the empty string when flexmark returns nothing, so an
    empty value is a silent generation failure rather than a notice with no docs.
    """
    empty = sorted(code for code, text in DESCRIPTIONS["descriptions"].items() if not text.strip())
    assert empty == []


def test_the_descriptions_are_rendered_html_not_raw_markdown() -> None:
    """What flexmark is for. Raw markdown here would reach the HTML report as
    literal asterisks and backticks.
    """
    text = DESCRIPTIONS["descriptions"]["attribution_without_role"]
    assert text.startswith("<p>")
    assert "`" not in text


# --- display_languages.json: the JDK's CLDR data, pinned to en-US ----------------


def test_the_languages_name_the_locale_they_were_rendered_in() -> None:
    """Divergence 17: `feedInfo["Feed Language"]` is fixed to English rather than
    following the host JVM's locale, and this file is how that is held. A
    regeneration under a different display locale would change every value.
    """
    assert LANGUAGES["_meta"]["display_locale"] == "en-US"
    assert "Locale.getDisplayLanguage" in LANGUAGES["_meta"]["method"]


def test_the_language_table_is_the_size_it_was_generated_at() -> None:
    assert len(LANGUAGES["languages"]) == 432


@pytest.mark.parametrize(
    ("tag", "name"),
    [
        ("en", "English"),
        ("fr", "French"),
        ("ja", "Japanese"),
        ("aar", "Afar"),
    ],
)
def test_an_anchor_language_renders_in_english(tag: str, name: str) -> None:
    """Three two-letter tags and one three-letter one, because the CLDR data has
    both forms and a generator bug could easily drop one family.
    """
    assert LANGUAGES["languages"][tag] == name
