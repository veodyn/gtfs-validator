"""The two most whitespace-sensitive regions of report.html.

Split from `htmlreport` for size. Everything here reproduces Thymeleaf output
that was read off the jar rather than derived from the template, because the
interesting parts are what Thymeleaf leaves *behind*:

- A removed `th:if` element leaves its line's indentation as a blank line, so
  `Service Window Start` renders as two runs of 28 spaces inside empty divs.
- `<th:block th:each>` emits the parent's leading text node once and then the
  block body per iteration, each ending on the block's own indentation. With one
  field that is a 40-space line, the field, then another 40-space line.
- `<p th:utext=...>` wraps flexmark output that already ends in a newline, so the
  closing `</p>` lands in column 0.
"""

from __future__ import annotations

from gtfs_validator.htmlreport import (
    MAX_ROWS,
    RULES_URL,
    _comment,
    _descriptions,
    esc,
    field_value,
    notices_map,
    unique_fields,
)
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.report import _defined
from gtfs_validator.summary import FeedFacts

HIDDEN_KEYS = ("Service Window Start", "Service Window End")
WINDOW_TOOLTIP = (
    "The range of service dates covered by the feed, based on trips with an "
    "associated service_id in calendar.txt and/or calendar_dates.txt"
)


def feed_info_cell(facts: FeedFacts) -> list[str]:
    """The Feed Info cell, which iterates the display-keyed map rather than the JSON one."""
    out = [
        '            <div class="summary-cell summary_info">',
        "                <h4>Feed Info</h4>",
        "                <hr />",
        "                <dl>",
    ]
    for key, value in facts.feed_info_display.items():
        out += ["                    <div>", "                        <div>"]
        if key in HIDDEN_KEYS:
            out += [" " * 28, " " * 28]
        else:
            out += [
                f"                            <dd >{esc(key)}:</dd>",
                "                            <dt>",
                *_url_span(key, value),
                ("                                <span>N/A</span>" if value == "" else " " * 32),
                (
                    " " * 32
                    if "URL" in key
                    else f"                                <span>{esc(value)}</span>"
                ),
                *_window_span(key),
                "                            </dt>",
            ]
        out += ["                        </div>", "                    </div>"]
    return [*out, "                </dl>", "            </div>"]


def _url_span(key: str, value: str) -> list[str]:
    if "URL" not in key or value == "":
        return [" " * 28]
    return [
        "                            <span>",
        (
            f'                                <a href="{esc(value)}" target="_blank" >'
            f"{esc(value)}</a>"
        ),
        "                            </span>",
    ]


def _window_span(key: str) -> list[str]:
    if key != "Service Window":
        return [" " * 32]
    return [
        "                                <span >",
        (
            '                                     <a href="#" class="tooltip" '
            'onclick="event.preventDefault();"><span>(?)</span>'
        ),
        (
            '                                        <span class="tooltiptext" '
            f'style="transform: translateX(-100%)">{WINDOW_TOOLTIP}</span>'
        ),
        "                                    </a>",
        "                                </span>",
    ]


def notice_table(container: NoticeContainer) -> list[str]:
    """The accordion table: one pair of rows per notice code, severity descending."""
    counts = _severity_counts(container)
    total = sum(counts.values())
    out = [
        f"    <h3><span>{total}</span> notices reported",
        f"        (<span>{counts.get('ERROR', 0)}</span> errors,",
        f"        <span>{counts.get('WARNING', 0)}</span> warnings,",
        f"        <span>{counts.get('INFO', 0)}</span> infos)",
        "    </h3>",
        "",
        '    <table class="accordion">',
        "        <thead>",
        "        <tr>",
        "            <th>Notice Code</th>",
        "            <th>Severity</th>",
        "            <th>Total</th>",
        "        </tr>",
        "        </thead>",
        "        <tbody>",
    ]
    for severity, by_code in notices_map(container).items():
        out.append("        <span>")
        for code, notices in by_code.items():
            out.append("            <span>")
            out += _code_block(code, severity.name, notices)
            out.append("            </span>")
        out.append("        </span>")
    return [*_join_repeats(out), "        </tbody>", "    </table>"]


def _join_repeats(lines: list[str]) -> list[str]:
    """Close and reopen a repeated element on one line, as Thymeleaf does.

    `th:each` repeats the element with no separator between iterations, so the
    closing tag of one and the opening tag of the next share a line:
    `            </span><span>`. Emitting them on separate lines is two bytes of
    difference per notice code, which the HTML comparison reports.
    """
    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        if merged and stripped == "<span>" and merged[-1].strip() == "</span>":
            indent = len(merged[-1]) - len(merged[-1].lstrip())
            previous = len(line) - len(line.lstrip())
            if indent == previous:
                merged[-1] += "<span>"
                continue
        merged.append(line)
    return merged


def _severity_counts(container: NoticeContainer) -> dict[str, int]:
    counts: dict[str, int] = {}
    for notices in container.grouped().values():
        name = notices[0].severity.name
        counts[name] = counts.get(name, 0) + len(notices)
    return counts


def _code_block(code: str, severity: str, notices: list) -> list[str]:
    fields = unique_fields(notices)
    truncation = (
        f"                             <p>Only the first {MAX_ROWS} of "
        f"<span>{len(notices)}</span> affected records are displayed below.</p>"
        if len(notices) > MAX_ROWS
        else "                             "
    )
    return [
        '                <tr class="notice">',
        f"                    <td >{esc(code)}</td>",
        f'                    <td class="{severity.lower()}" >{severity}</td>',
        f"                    <td >{len(notices)}</td>",
        "                </tr>",
        '                <tr class="description">',
        '                    <td colspan="4">',
        '                        <div class="desc-content">',
        f"                            <h3 >{esc(code)}</h3>",
        f"                            <p >{_descriptions().get(code, '')}</p>",
        "                            <p> You can see more about this notice <a",
        f'                                    href="{RULES_URL}#{esc(code)}-rule">here</a>.',
        "                            </p>",
        truncation,
        "                            <table>",
        "                                <thead>",
        "                                    <tr>",
        *_head_cells(code, fields),
        "                                    </tr>",
        "                                </thead>",
        "                                <tbody>",
        *_body_rows(notices, fields),
        "                                </tbody>",
        "                            </table>",
        "                        </div>",
        "                    </td>",
        "                </tr>",
    ]


def _head_cells(code: str, fields: list[str]) -> list[str]:
    out = [" " * 40]
    for name in fields:
        out += [
            "                                            <th>",
            f"                                                <span>{esc(name)}</span>",
            (
                '                                                <a href="#" class="tooltip" '
                'onclick="event.preventDefault();"><span>(?)</span>'
            ),
            (
                '                                                    <span class="tooltiptext">'
                f"{esc(_comment(code, name))}</span>"
            ),
            "                                                </a>",
            "                                            </th>",
            " " * 40,
        ]
    return out


def _body_rows(notices: list, fields: list[str]) -> list[str]:
    out: list[str] = []
    for notice in notices[:MAX_ROWS]:
        context = _defined(notice.context)
        out.append("                                    <tr>")
        out.append(" " * 40)
        for name in fields:
            rendered = field_value(context[name]) if name in context else "N/A"
            out.append(f"                                            <td >{rendered}</td>")
            out.append(" " * 40)
        out.append("                                    </tr>")
    return out
