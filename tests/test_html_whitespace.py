"""What Thymeleaf leaves behind when a `th:each` runs zero times, or many.

The golden page in test_html_golden.py pins one feed's report, and every list on
it happens to be non-empty and short. That is exactly the shape these artefacts
hide in, so this file asserts the edges of each loop instead: none, several, and
past the sample cap. Every expectation was measured against the pinned jar on a
probe feed, named in each test.

The rule that emerged, and that these tests hold in place: an empty loop still
emits the text node in front of the element, which ends in that element's own
indentation, so it becomes one blank-looking line. Iterations after the first are
separated by that same indentation for `<li>`, `<tr>` and `<div>` elements, and
not separated at all for `<span>`, which is how Thymeleaf treats inline elements.
An iteration a `th:if` removes leaves the indentation and nothing else.
"""

from __future__ import annotations

from dataclasses import replace

from gtfs_validator.htmlnotices import notice_table
from gtfs_validator.htmlsummary import summary_block
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from test_html_golden import FACTS

FEATURE_URLS = {
    "Route Colors": "https://gtfs.org/getting_started/features/base_add-ons/#route-colors",
    "Headsigns": "https://gtfs.org/getting_started/features/base_add-ons/#headsigns",
}


def test_an_empty_agency_list_keeps_its_indentation_line() -> None:
    """Measured on minimal.zip with a zero-byte agency.txt: the jar's page carries a
    20-space line inside the <ul>, and the two pages are otherwise identical."""
    page = summary_block(replace(FACTS, agencies=[]))
    opening = page.index("                <ul>")
    assert page[opening + 1] == " " * 20
    assert page[opening + 2] == "                </ul>"


def test_an_empty_file_list_keeps_its_indentation_line() -> None:
    """Measured on probe `macfeed_other`, a zip whose wrapper folder is not named
    after the archive, so nothing at all is listed at the root."""
    page = summary_block(replace(FACTS, files=[]))
    opening = page.index("                <ol>")
    assert page[opening + 1] == " " * 20
    assert page[opening + 2] == "                </ol>"


def test_features_are_emitted_back_to_back() -> None:
    """`<span>` is inline, so Thymeleaf drops the whitespace between iterations.

    Measured on a feed with seven features: the jar writes
    `</span><span class="spec-feature">` six times. It holds for features adjacent
    in the map (Route Colors then Headsigns) as much as for ones with skipped
    entries between them, so it is not an artefact of the th:if.
    """
    page = summary_block(
        replace(FACTS, gtfs_features=["Route Colors", "Headsigns"], feature_urls=FEATURE_URLS)
    )
    assert '                    </span><span class="spec-feature">' in page
    assert page.count('                    <span class="spec-feature">') == 1


def test_an_empty_features_list_keeps_its_indentation_line() -> None:
    page = summary_block(replace(FACTS, gtfs_features=[], feature_urls={}))
    opening = page.index("                <div>")
    assert page[opening + 1] == " " * 20


def test_a_report_with_no_notices_keeps_the_loop_indentation() -> None:
    """Measured on a feed the jar reports nothing about: between <tbody> and
    </tbody> there is one 8-space line and nothing else."""
    table = notice_table(NoticeContainer())
    body = table.index("        <tbody>")
    assert table[body + 1] == " " * 8
    assert table[body + 2] == "        </tbody>"


def test_rows_past_the_cap_leave_one_indentation_line_each() -> None:
    """The cap is a th:if on the row, not a slice, so the iterations still happen.

    Measured on a feed carrying 60 unknown files: the jar writes fifty rows and
    then ten 36-space lines before </tbody>.
    """
    container = NoticeContainer(max_exports_per_type=60)
    for index in range(60):
        container.add(Notice("unknown_file", Severity.INFO, {"filename": f"extra{index}.md"}))
    table = notice_table(container)
    page = "\n".join(table)
    assert "extra49.md" in page
    assert "extra50.md" not in page
    last_row = len(table) - 1 - table[::-1].index("                                    </tr>")
    trailing = 0
    while table[last_row + 1 + trailing] == " " * 36:
        trailing += 1
    assert trailing == 10
