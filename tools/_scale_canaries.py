"""The canary checks `measure_scale` runs on the synthetic feed's report.

Split from `measure_scale` when that file passed the size limit. The division is by responsibility:
this module decides whether a report shows the rules actually ran, and knows nothing about building
the feed, timing it, or the ceilings. `measure_scale` keeps the measurement and the CLI.

Every one of these exists because a rule was once certified "within ceilings" without having run.
A rule that reports nothing on a well-formed feed is indistinguishable from a rule that was skipped,
so each of these plants an outcome and requires exactly it.
"""

from __future__ import annotations

import json
from pathlib import Path

from _scale_dimensions import (
    CANARY_AGENCY,
    CANARY_LOCATION_GROUP,
    CANARY_TRIP,
    PATHWAY_PLATFORMS,
    SHAPES,
    STOPS,
)


def unmeasured_scans(report: Path) -> list[str]:
    """Fail if any of the early-exiting scans reported, because one report ends the scan.

    The travel-speed span scan is quadratic in a trip's stop times and a reported pair *returns*
    from it, so a notice really does end the measurement. The block scan is different: reporting
    a pair does not end anything, and three mutually overlapping trips still report all three
    pairs. What ends the block scan is the `break` on a non-overlapping successor, which is why
    the feed's blocks overlap in time and stay silent through their services instead. A notice
    there is a signal that the feed stopped being the feed this harness was calibrated on, not
    that the scan exited: either way the number printed no longer measures what it claims.

    Checking the elapsed time cannot notice either case, because a faster run is what both look
    like. The headsign scan needs the opposite test, which is `headsign_canary` below.

    The whole feed is built to be silent on these codes rather than only the trips that matter,
    which keeps this independent of the 1,000-sample cap. `totalNotices` would be reliable above
    the cap but the trip ids in `sampleNotices` would not, and picking through samples to decide
    which trip a notice belongs to is a second thing to get wrong.
    """
    codes = {
        "fast_travel_between_consecutive_stops",
        "fast_travel_between_far_stops",
        "block_trips_with_overlapping_stop_times",
    }
    reported = [
        f"{notice['code']} x{notice['totalNotices']}"
        for notice in json.loads(report.read_text())["notices"]
        if notice["code"] in codes
    ]
    if not reported:
        return []
    return [f"the feed reported {', '.join(reported)}, so it no longer measures what it claims"]


def headsign_canary(report: Path) -> list[str]:
    """Require exactly one headsign notice, from the last trip in trips.txt.

    The other early exits announce themselves by a notice. This one does the reverse: upstream's
    circular-trip test `return`s from the whole validator, so one circular trip near the top of
    trips.txt leaves every later trip unvisited and the report *silent*. Silence is what a working
    scan and an abandoned one both look like, which is exactly the trap that had two other rules
    certified "within ceilings" without having run.

    So the feed plants a notice on its last trip instead. Seeing it is evidence that the loop
    reached the end of trips.txt; not seeing it means the scan stopped somewhere in the middle and
    the elapsed time no longer covers this rule. See `_scale_feed.CANARY_HEADSIGN`.
    """
    notices = [
        notice
        for notice in json.loads(report.read_text())["notices"]
        if notice["code"] == "trip_headsign_matches_intermediate_stop"
    ]
    total = sum(notice["totalNotices"] for notice in notices)
    if total != 1:
        return [
            (
                f"the headsign canary reported {total} times rather than once, so the trip "
                "scan did not run to the end of trips.txt"
            )
        ]
    trips = {sample["tripId"] for notice in notices for sample in notice["sampleNotices"]}
    if trips != {CANARY_TRIP}:
        return [f"the headsign notice came from {sorted(trips)} rather than {CANARY_TRIP}"]
    return []


def shape_matching_canary(report: Path) -> list[str]:
    """Require one too-far notice per (shape, stop), which is what a completed matching produces.

    The same trap as the headsign canary, and the third time this harness has fallen into it: the
    feed carried no shapes.txt at all, so `ShapeToStopMatchingValidator` did nothing and the
    elapsed time covered none of it. Silence would look identical to a working run.

    The count is exact rather than a lower bound, and that is the point of it. The feed's shapes run
    nowhere near its stops, so every stop the matching reaches is too far, and the notice is
    deduplicated per shape and stop: `SHAPES * STOPS` and no more, however many trips visit them. A
    larger number means the deduplication stopped working, a smaller one means the walk did not
    reach every shape, and either way the elapsed time no longer measures the scan this feed exists
    to time.

    **What it cannot see**, and a review said so: the trip fingerprint collapses repeated stop
    patterns, so this number is reached whether 24,020 trips were matched or the 4,000 surviving
    patterns were. That is upstream's behaviour rather than a fault, so there is nothing here to
    catch; the count that would change if the fingerprint broke is in
    `tests/test_rules_stop_to_shape_walk.py`, where three mutations of it are each caught.

    `totalNotices` is read rather than the samples, because the count is far above the 1,000-sample
    cap.
    """
    total = sum(
        notice["totalNotices"]
        for notice in json.loads(report.read_text())["notices"]
        if notice["code"] == "stop_too_far_from_shape"
    )
    # Only the stops a trip actually visits are matched. `_walked` turns round rather than
    # wrapping, so the four-stop trips reach a prefix of the list and the long trips reach all of
    # it; every shape sees the same set, which is every stop.
    expected = SHAPES * STOPS
    if total != expected:
        return [
            (
                f"the shape-matching canary reported {total} times rather than {expected}, so the "
                "stop-to-shape scan did not run over every shape or stopped deduplicating"
            )
        ]
    return []


def reachability_canary(report: Path) -> list[str]:
    """Require exactly one unreachable location, the platform the feed leaves unconnected.

    The fourth rule to need one of these. `PathwayReachableLocationValidator` does nothing at all
    for a feed with no `pathways.txt`, and this feed had none, so the run covered none of it.

    Exactly one rather than at least one, in both directions. A station where every platform is
    reachable is silent, and silence cannot tell a working traversal from an absent one; more than
    one means the traversal stopped reaching platforms it should reach.

    The station is wired so that this really does catch the two failures the sentence above claims.
    Its platforms sit two hops from an entrance behind a generic node, so losing the transitive hop
    reports all hundred, and half its pathway rows are written platform-first, so losing the
    bidirectional test in the reverse-direction traversal reports the other half. A review found the
    first version of the station could detect neither, because every platform was adjacent to an
    entrance and every row was written entrance-first.

    Both flags are checked too. The count and the id alone accept a notice claiming the platform is
    reachable in one direction, which is a different finding from the one this pins.
    """
    notices = [
        notice
        for notice in json.loads(report.read_text())["notices"]
        if notice["code"] == "pathway_unreachable_location"
    ]
    total = sum(notice["totalNotices"] for notice in notices)
    if total != 1:
        return [
            (
                f"the reachability canary reported {total} times rather than once, so the pathway "
                "traversal did not reach every platform it should"
            )
        ]
    unreachable = f"PWP{PATHWAY_PLATFORMS - 1}"
    reported = {
        (sample["stopId"], sample["hasEntrance"], sample["hasExit"])
        for notice in notices
        for sample in notice["sampleNotices"]
    }
    if reported != {(unreachable, False, False)}:
        expected = [(unreachable, False, False)]
        return [f"the reachability notice was {sorted(reported)} rather than {expected}"]
    return []


def foreign_key_canary(report: Path) -> list[str]:
    """Require exactly the two planted foreign key violations, from two different child tables.

    Exactly two in both directions. Every other one of the fifty references in this feed resolves, so
    more than two means a check reported where it should be quiet, and fewer means the checks did not
    run: the feed carried no attributions.txt at all before this canary, and a run that skipped all
    fifty would still have printed "within ceilings".

    Two child tables rather than one, because a review pointed out that a single planted violation
    proves only that `attributions.agency_id` ran, which is one row against a two-row table. The
    second is on `stop_times.txt`, the largest table in the feed, so the anti-join whose cost actually
    matters is the one being observed. Skipping it changes the count.

    The context is checked too, not just the count, because notices about some other reference would
    satisfy a bare count while proving nothing about the two this plants.

    **What it cannot see.** Three mutations were run against the single-violation version and only the
    first was caught, so the other two are named here rather than left to be assumed:

    - the rule reporting nothing at all: caught, 0 rather than the expected count;
    - the `hasColumn` gate removed: **not** caught, since a column absent from the header holds NULL
      in every row and the anti-join skips it either way. What that gate buys is a scan not run, which
      is pinned by
      `tests/test_rules_foreign_key.py::test_a_column_the_file_never_declared_is_not_queried_at_all`;
    - the anti-join's NULL handling on the parent subquery removed: **not** caught, because every
      parent column in this feed is fully populated, which is what a valid feed looks like. A feed
      whose parent key were sometimes empty would go silent on that whole reference. Covered by
      `tests/test_store_references.py::test_a_null_parent_key_does_not_silence_every_notice`.
    """
    notices = [
        notice
        for notice in json.loads(report.read_text())["notices"]
        if notice["code"] == "foreign_key_violation"
    ]
    total = sum(notice["totalNotices"] for notice in notices)
    expected = {
        ("attributions.txt", "agency_id", CANARY_AGENCY),
        ("stop_times.txt", "location_group_id", CANARY_LOCATION_GROUP),
    }
    if total != len(expected):
        return [
            (
                f"the foreign key canary reported {total} times rather than {len(expected)}, so the "
                "reference checks did not run over this feed as calibrated"
            )
        ]
    reported = {
        (sample["childFilename"], sample["childFieldName"], sample["fieldValue"])
        for notice in notices
        for sample in notice["sampleNotices"]
    }
    if reported != expected:
        return [f"the foreign key notices were {sorted(reported)} rather than {sorted(expected)}"]
    return []
