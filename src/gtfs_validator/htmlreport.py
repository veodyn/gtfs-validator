"""`report.html`, rendered to match Thymeleaf's output byte for byte.

The head and the tail of upstream's template are static and are emitted from the
vendored copy in `data/report_template.html`, so they cannot drift by
transcription. Only line 2 changes: Thymeleaf drops its own namespace, so
`<html xmlns:th="...">` becomes `<html>`. Measured: lines 1 to 227 and 386 to 396
of the template are otherwise identical to the rendered page.

The body is emitted here, because reproducing Thymeleaf means reproducing its
artefacts and those are not derivable from the template by any general rule:

- `<span th:text="${x}" />`, a self-closing tag, renders as `<span >...</span>`
  with a space where the attribute was.
- `<td th:text="..." />` likewise renders `<td >...</td>`.
- An element removed by a false `th:if` leaves its line's leading indentation
  behind as a blank line, rather than removing the line.
- `th:block` leaves its indentation behind on both the opening and closing line.
- Escaping is Java's: an apostrophe is `&#39;`, where Python's `html.escape`
  writes `&#x27;`.

Notice descriptions are not rendered here either. `th:utext` writes flexmark's
Markdown output unescaped, and that is measured per code at the pin into
`data/notice_descriptions.json`.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from gtfs_validator.notices import NoticeContainer, Severity
from gtfs_validator.report import _defined
from gtfs_validator.summary import FeedFacts, RunConfig

DATA = Path(__file__).resolve().parent / "data"
TEMPLATE = DATA / "report_template.html"

# The template's static halves, by line number. The tail starts at the `<br>`
# before the footer, not at `</body>`: the footer is static markup and belongs to
# the copied region. Asserted in tests against the vendored file so a template
# bump fails loudly rather than rendering nonsense.
HEAD_LINES = 227
TAIL_FROM = 382

RULES_URL = "https://gtfs-validator.mobilitydata.org/rules.html"
MAX_ROWS = 50


@cache
def _descriptions() -> dict[str, str]:
    text = (DATA / "notice_descriptions.json").read_text(encoding="utf-8")
    return json.loads(text)["descriptions"]


@cache
def _schema() -> dict[str, dict]:
    return json.loads((DATA / "notice_schema.json").read_text(encoding="utf-8"))


def esc(value: object) -> str:
    """Thymeleaf's HTML escaping, which spells the apostrophe `&#39;`."""
    text = str(value)
    for needle, replacement in (
        ("&", "&amp;"),
        ("<", "&lt;"),
        (">", "&gt;"),
        ('"', "&quot;"),
        ("'", "&#39;"),
    ):
        text = text.replace(needle, replacement)
    return text


def field_value(value: object) -> str:
    """`getValueForField`, rendered as the JSON value it is.

    Measured: a string context value reaches the page carrying its JSON quotes,
    as `&quot;feed_info.txt&quot;`. So the value is serialised before escaping,
    not formatted for a human.
    """
    return esc(json.dumps(value, ensure_ascii=False))


def _comment(code: str, field: str) -> str:
    """`getCommentForField`: the field's description from the notice schema."""
    entry = _schema().get(code) or {}
    prop = (entry.get("properties") or {}).get(field) or {}
    return prop.get("description") or ""


def notices_map(container: NoticeContainer) -> dict[Severity, dict[str, list]]:
    """`summary.noticesMap`: severity descending, then code ascending.

    A `TreeMap` on `SeverityLevel` with `Comparator.reverseOrder()`, and the enum
    declares INFO, WARNING, ERROR, so the page runs ERROR, WARNING, INFO. Codes
    inside each are a plain `TreeMap`, so alphabetical.
    """
    by_severity: dict[Severity, dict[str, list]] = {}
    for notices in container.grouped().values():
        first = notices[0]
        by_severity.setdefault(first.severity, {})[first.code] = list(notices)
    return {
        severity: dict(sorted(codes.items()))
        for severity, codes in sorted(by_severity.items(), reverse=True)
    }


def unique_fields(notices: list) -> list[str]:
    """`getUniqueFieldsForCodes`: the first notice's field order, filtered.

    Upstream collects the fields that any notice of this code actually sets, then
    walks the *first* notice's full field list and keeps those. So the order is
    the first notice's and the membership is the whole group's.
    """
    populated = {field for notice in notices for field in _defined(notice.context)}
    return [field for field in notices[0].context if field in populated]


def _header(config: RunConfig, validated_at: str, different_date: bool) -> list[str]:
    country = (
        ". No country code was provided."
        if config.country_code == "ZZ"
        else f", with the country code: {config.country_code}."
    )
    different = (
        f"<span>The date used during validation was {esc(config.date_for_validation)}.</span>"
        if different_date
        else ""
    )
    return [
        "    <h1>GTFS Schedule Validation Report</h1>",
        (
            '    <p>This report was generated by the <a href="https://github.com/MobilityData/'
            'gtfs-validator">Canonical GTFS Schedule'
        ),
        "        validator</a>,",
        (
            f"        <span>version {esc(config.validator_version)}</span> at "
            f"<span>{esc(validated_at)}</span>,"
        ),
        "        <br/>",
        "        for the dataset",
        f"        <span>{esc(config.gtfs_input)}</span><span>{esc(country)}</span>",
        "        </br>",
        f"        {different}</p>",
        "",
        f'    <p>Use this report alongside our <a href="{RULES_URL}">documentation</a>.</p>',
        "",
        "    ",
        "",
        "    <h2>Summary</h2>",
        "",
    ]


def _summary_block(facts: FeedFacts) -> list[str]:
    """The five summary cells. Absent entirely when there is no feed metadata.

    `htmlnotices` reads this module's helpers, so its import happens here rather
    than at module scope to keep the cycle from closing at import time.
    """
    from gtfs_validator.htmlnotices import feed_info_cell

    out = ['    <div class="summary">', '        <div class="summary-row">']
    out += [
        '            <div class="summary-cell summary_info">',
        "                <h4>Agencies included</h4>",
        "                <hr />",
        "                <ul>",
    ]
    for agency in facts.agencies:
        email = "Not provided" if not agency["email"] else agency["email"]
        out += [
            "                    <li>",
            f"                        <span>{esc(agency['name'])}</span>",
            "                        <ul>",
            (
                f"                            <li><b>website: </b>"
                f'<a href="{esc(agency["url"])}">{esc(agency["url"])}</a></li>'
            ),
            (
                f"                            <li><b>phone number: </b>"
                f"<span >{esc(agency['phone'])}</span></li>"
            ),
            f"                            <li><b>email: </b><span >{esc(email)}</span></li>",
            "                        </ul>",
            "                    </li>",
        ]
    out += ["                </ul>", "            </div>"]
    out += feed_info_cell(facts)
    out += _files_cell(facts) + _counts_cell(facts) + _features_cell(facts)
    out += ["        </div>", "    </div>"]
    return out


def _files_cell(facts: FeedFacts) -> list[str]:
    out = [
        '            <div class="summary-cell summary_list">',
        "                <h4>Files included</h4>",
        "                <hr />",
        "                <ol>",
    ]
    out += [f"                    <li>{esc(name)}</li>" for name in facts.files]
    return [*out, "                </ol>", "            </div>"]


def _counts_cell(facts: FeedFacts) -> list[str]:
    out = [
        '            <div class="summary-cell summary_list">',
        "                <h4>Counts</h4>",
        "                <hr />",
        "                <ul>",
    ]
    out += [
        f"                    <li><span >{esc(label)}: {esc(value)}</span></li>"
        # Alphabetical here and declaration-ordered in the JSON: the page walks
        # FeedMetadata's TreeMap directly, where report.json goes through
        # JsonReportCounts' declared fields. Measured, the two really do differ.
        for label, value in sorted(facts.counts.items())
    ]
    return [*out, "                </ul>", "            </div>"]


def _features_cell(facts: FeedFacts) -> list[str]:
    out = [
        '            <div class="summary-cell summary_list" id="gtfs-features-container">',
        "                <h4>",
        "                    GTFS Features included",
        (
            '                    <a href="#" class="tooltip" '
            'onclick="event.preventDefault();"><span>(?)</span>'
        ),
        (
            '                        <span class="tooltiptext" '
            'style="transform: translateX(-100%)">GTFS features provide a standardized '
            "vocabulary to define and describe features that are officially adopted in "
            "GTFS.</span>"
        ),
        "                    </a>",
        "                </h4>",
        "                <hr />",
        "                <div>",
    ]
    # The text node before `<span th:each>` is emitted once and ends in the
    # element's indentation, so it opens the first iteration's line rather than
    # standing alone. It is only a line of its own when the loop runs zero times.
    if not facts.gtfs_features:
        return [*out, " " * 20, "                </div>", "            </div>"]
    for name in facts.gtfs_features:
        out += [
            '                    <span class="spec-feature">',
            (
                f'                        <a href="{esc(facts.feature_urls[name])}" '
                f'target="_blank">{esc(name)}</a>'
            ),
            "                    </span>",
        ]
    return [*out, "                </div>", "            </div>"]


def render(
    notices: NoticeContainer,
    facts: FeedFacts | None,
    config: RunConfig,
    validated_at: str,
    different_date: bool,
) -> str:
    from gtfs_validator.htmlnotices import notice_table

    lines = TEMPLATE.read_text(encoding="utf-8").split("\n")
    head = lines[:HEAD_LINES]
    head[1] = "<html>"
    body = ["<body>", *_header(config, validated_at, different_date)]
    if facts is not None:
        body += _summary_block(facts)
    body += ["", "", "    <h2>Specification Compliance report</h2>", ""]
    body += notice_table(notices)
    tail = lines[TAIL_FROM - 1 :]
    return "\n".join([*head, *body, *tail])


def write(
    path: Path,
    *,
    notices: NoticeContainer,
    facts: FeedFacts | None,
    config: RunConfig,
    validated_at: str,
    different_date: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(notices, facts, config, validated_at, different_date), encoding="utf-8")
