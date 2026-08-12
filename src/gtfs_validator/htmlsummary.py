"""The five summary cells of `report.html`.

Split out of `htmlreport` when that file passed the size limit. The division is by
region of the page: this is everything between `<h2>Summary</h2>` and the
compliance report, `htmlnotices` is the table below it, and `htmlreport` owns the
static head and tail and the order the pieces go in.

Thymeleaf's whitespace artefacts are the whole reason these cells are written out
line by line rather than generated from the template; `htmlreport`'s docstring
lists them, and `_EMPTY_LOOP` is the one this file exists to get right.
"""

from __future__ import annotations

from gtfs_validator.htmlreport import esc
from gtfs_validator.summary import FeedFacts

# What a `th:each` over an empty collection leaves behind: the text node in front
# of the element survives, and it ends in that element's indentation, so the line
# is emitted with nothing on it. Every loop below sits at the same depth.
# Measured against the jar on a feed with no loadable agency and on one whose
# archive lists no files at all.
_EMPTY_LOOP = " " * 20


def summary_block(facts: FeedFacts) -> list[str]:
    """The five summary cells. Absent entirely when there is no feed metadata.

    `htmlnotices` reads `htmlreport`'s helpers, so its import happens here rather
    than at module scope to keep the cycle from closing at import time.
    """
    from gtfs_validator.htmlnotices import feed_info_cell

    out = ['    <div class="summary">', '        <div class="summary-row">']
    out += _agencies_cell(facts)
    out += feed_info_cell(facts)
    out += _files_cell(facts) + _counts_cell(facts) + _features_cell(facts)
    out += ["        </div>", "    </div>"]
    return out


def _agencies_cell(facts: FeedFacts) -> list[str]:
    out = [
        '            <div class="summary-cell summary_info">',
        "                <h4>Agencies included</h4>",
        "                <hr />",
        "                <ul>",
    ]
    if not facts.agencies:
        out.append(_EMPTY_LOOP)
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
    return [*out, "                </ul>", "            </div>"]


def _files_cell(facts: FeedFacts) -> list[str]:
    out = [
        '            <div class="summary-cell summary_list">',
        "                <h4>Files included</h4>",
        "                <hr />",
        "                <ol>",
    ]
    if not facts.files:
        out.append(_EMPTY_LOOP)
    out += [f"                    <li>{esc(name)}</li>" for name in facts.files]
    return [*out, "                </ol>", "            </div>"]


def _counts_cell(facts: FeedFacts) -> list[str]:
    out = [
        '            <div class="summary-cell summary_list">',
        "                <h4>Counts</h4>",
        "                <hr />",
        "                <ul>",
    ]
    # No empty case: FeedMetadata puts all six counts in whatever the feed holds,
    # so this loop cannot run zero times. Same for the Feed Info cell's map.
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
    if not facts.gtfs_features:
        return [*out, _EMPTY_LOOP, "                </div>", "            </div>"]
    # This loop, alone among the six, emits its iterations back to back: the
    # whitespace in front of the span appears once and the next span opens on the
    # line that closed the last one. Measured on a feed with seven features, where
    # the jar writes `</span><span class="spec-feature">` six times, and it holds
    # for features that are adjacent in the map as well as for ones with skipped
    # entries between them. The <li> and <tr> loops keep their per-iteration
    # indentation, measured on two agencies and on sixty notice rows, so this is
    # not a rule about th:each in general.
    opening = '<span class="spec-feature">'
    for position, name in enumerate(facts.gtfs_features):
        if position:
            out[-1] += opening
        else:
            out.append(f"                    {opening}")
        out += [
            (
                f'                        <a href="{esc(facts.feature_urls[name])}" '
                f'target="_blank">{esc(name)}</a>'
            ),
            "                    </span>",
        ]
    return [*out, "                </div>", "            </div>"]
