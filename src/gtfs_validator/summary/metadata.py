"""`summary.counts`, `agencies` and `feedInfo`, ported from `FeedMetadata`.

Every shape here was read off the jar rather than inferred, on a feed carrying
agency.txt, calendar.txt and no feed_info.txt:

    "counts":   {"Shapes": 0, "Stops": 1, ..., "Blocks": 0}
    "agencies": [{"name": ..., "url": ..., "phone": "", "email": "", "timezone": ...}]
    "feedInfo": {"publisherName": "", ..., "feedServiceWindowStart": "2026-01-01"}

Two details that reading only the Java would have got wrong. `getTableForFilename`
returns a container for a *missing* file too, so `loadFeedInfo` runs on a feed with
no feed_info.txt and writes empty strings rather than leaving the keys out. And
Gson omits nulls, so a key that was never `put` disappears from the JSON entirely
while a key `put` as `""` stays. The two are different states and the report shows
the difference.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from gtfs_validator.rules._shared.calendars import to_date
from gtfs_validator.rules._shared.service_window import total_service_window
from gtfs_validator.rules.feedview import FeedView
from gtfs_validator.summary.reads import table_rows

DATA = Path(__file__).resolve().parent.parent / "data"

# `JsonReportCounts`' field declaration order, which is what Gson serialises.
# The `counts` map upstream is a TreeMap, but it is re-read into declared fields
# on the way out, so its sorted order never reaches the file.
COUNT_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("Shapes", "shapes.txt", "shape_id"),
    ("Stops", "stops.txt", "stop_id"),
    ("Routes", "routes.txt", "route_id"),
    ("Trips", "trips.txt", "trip_id"),
    ("Agencies", "agency.txt", "agency_id"),
    ("Blocks", "trips.txt", "block_id"),
)

AGENCY_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "agency_name"),
    ("url", "agency_url"),
    ("phone", "agency_phone"),
    ("email", "agency_email"),
    ("timezone", "agency_timezone"),
)


@cache
def _display_languages() -> dict[str, str]:
    text = (DATA / "display_languages.json").read_text(encoding="utf-8")
    return json.loads(text)["languages"]


def display_language(tag: str | None) -> str:
    """`Locale.getDisplayLanguage()` at the `en-US` display locale.

    Only the primary subtag decides the answer, so `zh-Hant` and `zh` both give
    "Chinese". A subtag the JDK has no name for echoes back unchanged, which is
    what `getDisplayLanguage` itself does.
    """
    if not tag:
        return ""
    primary = tag.replace("_", "-").split("-", 1)[0].lower()
    return _display_languages().get(primary, primary)


def counts(view: FeedView) -> dict[str, int]:
    """Six counts of *unique non-empty* ids, not of rows.

    `Blocks` reads trips.txt's block_id, so a feed whose trips declare no block
    reports 0 while `Trips` reports the row count. Measured on a feed with one
    trip and no block_id column: `{"Trips": 1, "Blocks": 0}`.
    """
    found: dict[str, int] = {}
    for label, filename, column in COUNT_SOURCES:
        unique: set[object] = set()
        for row in table_rows(view, filename):
            value = row.get(column)
            if value is not None and value != "":
                unique.add(value)
        found[label] = len(unique)
    return found


def agencies(view: FeedView) -> list[dict[str, str]]:
    """One entry per agency.txt row, in file order, with absent fields as ""."""
    return [
        {label: str(row.get(column) or "") for label, column in AGENCY_FIELDS}
        for row in table_rows(view, "agency.txt")
    ]


def _service_window(view: FeedView) -> tuple[str, str, str]:
    """The window as (combined, start, end), all "" when it cannot be computed.

    Upstream gates on trips.txt plus at least one of calendar.txt and
    calendar_dates.txt having parsed, then swallows any exception from the
    computation and writes empty strings in a `finally`. Both halves matter: the
    gate keeps a feed with no calendars out, and the swallow keeps a summary
    failure from taking the whole report down with it.
    """
    has_calendar = not view.is_missing("calendar.txt") and not view.dependency_failed(
        "calendar.txt"
    )
    has_dates = not view.is_missing("calendar_dates.txt") and not view.dependency_failed(
        "calendar_dates.txt"
    )
    trips_ok = not view.is_missing("trips.txt") and not view.dependency_failed("trips.txt")
    if not trips_ok or not (has_calendar or has_dates):
        return ("", "", "")
    try:
        window = total_service_window(view)
    except Exception:  # noqa: BLE001 - upstream logs and carries on with empty strings
        return ("", "", "")
    if window is None:
        return ("", "", "")
    start, end = window
    return (f"{start} to {end}", str(start), str(end))


def feed_info(view: FeedView) -> dict[str, str]:
    """`JsonReportFeedInfo`, in its field declaration order, with nulls dropped.

    The keys `put` only under a condition are the ones that can disappear:
    the two dates need feed_info.txt to declare the columns, and the two service
    window bounds need the gate above to pass. Everything else is written even
    when there is no feed_info.txt at all.
    """
    rows = list(table_rows(view, "feed_info.txt"))
    first = rows[0] if rows else None
    info: dict[str, str] = {
        "publisherName": str(first.get("feed_publisher_name") or "") if first else "",
        "publisherUrl": str(first.get("feed_publisher_url") or "") if first else "",
        "feedLanguage": display_language(first.get("feed_lang")) if first else "",
    }
    # The store holds a DATE as a YYYYMMDD integer so SQL ordering is correct,
    # and this field is rendered ISO, so every value converts on the way out.
    # Upstream's own "absent" marker is the epoch, because an unset GtfsDate
    # defaults there and `checkLocalDate` maps exactly that back to "". Ours is
    # None, so the two spellings of absent both land on "".
    for key, column in (("feedStartDate", "feed_start_date"), ("feedEndDate", "feed_end_date")):
        if view.has_column("feed_info.txt", column) and first is not None:
            value = first.get(column)
            info[key] = "" if value is None else str(to_date(int(value)))
    info["feedEmail"] = str(first.get("feed_contact_email") or "") if first else ""

    _, start, end = _service_window(view)
    if start or end:
        info["feedServiceWindowStart"] = start
        info["feedServiceWindowEnd"] = end
    return info


def feed_info_display(view: FeedView) -> dict[str, str]:
    """The `feedInfo` map as `FeedMetadata` builds it, keyed for display.

    Two different objects share the name. The JSON carries `JsonReportFeedInfo`,
    whose keys are camelCase and which drops `Service Window`; the HTML page
    iterates *this* map, whose keys are the human labels and which keeps it. So
    the page shows `Service Window` and hides the two bounds, and the JSON does
    the opposite. Insertion order is upstream's `put` order, which is the order
    the page renders.
    """
    rows = list(table_rows(view, "feed_info.txt"))
    first = rows[0] if rows else None
    info: dict[str, str] = {
        "Publisher Name": str(first.get("feed_publisher_name") or "") if first else "",
        "Publisher URL": str(first.get("feed_publisher_url") or "") if first else "",
        "Feed Email": str(first.get("feed_contact_email") or "") if first else "",
        "Feed Language": display_language(first.get("feed_lang")) if first else "",
    }
    for label, column in (
        ("Feed Start Date", "feed_start_date"),
        ("Feed End Date", "feed_end_date"),
    ):
        if view.has_column("feed_info.txt", column) and first is not None:
            value = first.get(column)
            info[label] = "" if value is None else str(to_date(int(value)))
    combined, start, end = _service_window(view)
    if start or end or combined:
        info["Service Window"] = combined
        info["Service Window Start"] = start
        info["Service Window End"] = end
    return info


def service_window_label(view: FeedView) -> str:
    """`feedInfo["Service Window"]`: the two bounds joined by " to ".

    Present in the map upstream builds and absent from `JsonReportFeedInfo`, so
    it reaches the HTML page and never the JSON. Upstream joins with `" to "`
    after filtering nulls, so a window with one bound would render without the
    separator; in practice both bounds are set together or neither is.
    """
    return _service_window(view)[0]


def filenames(present: frozenset[str]) -> list[str]:
    """Every name the archive carried, sorted. Includes files GTFS does not define.

    Measured: a feed carrying `notes.md` lists it, so this is the archive's own
    listing rather than the set of tables that loaded.
    """
    return sorted(present)
