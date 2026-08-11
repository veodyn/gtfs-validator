"""`report.html`, pinned byte for byte.

The README's strongest claim is that this file is byte-identical to the jar's, and
until this test that claim rested entirely on `tools/diff_full_output_against_upstream.sh`,
which needs a 38 MB jar and a JDK. Those live in `/tmp` on a developer machine and
were pruned twice between 2026-07-29 and 2026-08-11, so the check protecting the
strongest claim was frequently the one that could not run.

This is not a substitute for that harness and cannot become one: the golden file
here is *our* output, so it pins the HTML against accidental change, not against
upstream. Establishing what upstream writes still takes the jar. What it buys is
that a refactor which quietly reflows the page fails in four seconds on every
machine rather than waiting for a differential nobody could run.

Regenerate deliberately, never to make a red test green:

    python tools/regenerate_html_golden.py

and read the diff before committing it. A changed golden is a changed report, and
the report's shape is a contract.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from gtfs_validator.htmlreport import render
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.summary import FeedFacts, RunConfig

GOLDEN = Path(__file__).resolve().parent / "golden/report.html"

# Every field fixed. `validated_at` is the one the CLI takes from the clock, which is
# why `render` accepts it rather than reading it: a golden file cannot pin a page
# that carries the current time.
CONFIG = RunConfig(
    validator_version="0.1.0",
    validated_at="2026-06-01T12:00:00-04:00",
    gtfs_input="minimal.zip",
    threads=1,
    output_directory="out",
    system_errors_report_name="system_errors.json",
    validation_report_name="report.json",
    html_report_name="report.html",
    country_code="US",
    date_for_validation=date(2026, 6, 1),
)

FACTS = FeedFacts(
    feed_info={"feed_start_date": "20260101", "feed_end_date": "20261231"},
    feed_info_display={"Feed Language": "English", "Service Window": "2026-01-01 to 2026-12-31"},
    agencies=[{"name": "Acme Transit", "url": "https://example.com", "phone": "", "email": ""}],
    files=["agency.txt", "calendar.txt", "routes.txt", "stop_times.txt", "stops.txt", "trips.txt"],
    counts={"Shapes": 0, "Stops": 1, "Routes": 1, "Trips": 1, "Agencies": 1, "Blocks": 0},
    gtfs_features=["Route Colors"],
    feature_urls={"Route Colors": "https://gtfs.org/getting_started/features/base_add_ons/"},
)


def build_notices() -> NoticeContainer:
    """One notice per severity, plus a capped code and a multi-field context.

    Chosen for what the *page* does rather than for feed realism: the three severity
    blocks render separately, a code above the sample cap renders its count rather
    than its rows, and a two-field context is what exercises the column headers.
    """
    container = NoticeContainer(max_exports_per_type=2)
    container.add(Notice("empty_file", Severity.ERROR, {"filename": "stops.txt"}))
    container.add(Notice("unknown_file", Severity.INFO, {"filename": "notes.md"}))
    for row in range(5):
        container.add(
            Notice(
                "leading_or_trailing_whitespaces",
                Severity.WARNING,
                {"filename": "stops.txt", "csvRowNumber": row + 2, "fieldValue": " S1 "},
            )
        )
    return container


def render_golden() -> str:
    return render(build_notices(), FACTS, CONFIG, CONFIG.validated_at, different_date=False)


def test_the_rendered_page_is_byte_identical_to_the_golden() -> None:
    assert render_golden() == GOLDEN.read_text(encoding="utf-8")


def test_a_capped_code_shows_its_total_rather_than_every_row() -> None:
    """Guards the golden against being regenerated into something meaningless.

    A golden file passes whatever it was generated from, including a page whose
    notice table silently stopped rendering. This asserts one thing the page must
    say, so an empty or truncated regeneration fails here as well.
    """
    page = render_golden()
    row = "<td >leading_or_trailing_whitespaces</td>\n"
    assert row in page
    # The count column, two cells further on: five emitted, two sampled, and it is
    # the total that the table reports.
    after = page.split(row, 1)[1]
    assert after.split("</tr>", 1)[0].count("<td >5</td>") == 1


def test_every_severity_present_in_the_container_reaches_the_page() -> None:
    page = render_golden()
    for severity in ("ERROR", "WARNING", "INFO"):
        assert severity in page
