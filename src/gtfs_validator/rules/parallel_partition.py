"""How the parallel runner divides its work, and the indexes it wants first.

Split from `parallel_runner` when the two together passed the file-size limit. The
division is by responsibility: everything here decides *who runs what*, and none of
it touches a row or a notice, so it cannot move output, only speed.
"""

from __future__ import annotations

# Rules that share a cached derivation (`feed.cache`) must land in the same worker,
# or the derivation reruns once per worker that touches the cohort: the first
# round-robin split scattered the four stop-to-shape codes across four workers and
# each of them walked every shape. Grouping only moves speed, never output; codes
# absent from every cohort are singletons. Built by grepping each `_shared` module
# with a cache for its importers; keep in step when a rule joins a cached helper.
CACHE_COHORTS = (
    # One cohort, not two: the shape-distance rules share `shape_points.by_shape`
    # with the stop-to-shape walk, and a review measured the grouped shapes scan
    # repeating across workers when they were split. The cheap `trip_ids` cache is
    # deliberately NOT merged the same way: fusing all its consumers would build
    # one serial mega-cohort, and re-deriving it is a single indexed scan.
    (
        "stop_has_too_many_matches_for_shape",
        "stop_too_far_from_shape",
        "stops_match_shape_out_of_order",
        "stop_too_far_from_shape_using_user_distance",
        "decreasing_shape_distance",
        "equal_shape_distance_same_coordinates",
        "equal_shape_distance_diff_coordinates",
        "equal_shape_distance_diff_coordinates_distance_below_threshold",
    ),
    ("fast_travel_between_consecutive_stops", "fast_travel_between_far_stops"),
    (
        "location_with_unexpected_stop_time",
        "stop_without_stop_time",
        "unsorted_stop_times",
        "unused_trip",
    ),
    (
        "transfer_with_invalid_stop_location_type",
        "transfer_with_suspicious_mid_trip_in_seat",
        "transfer_with_invalid_trip_and_stop",
        "transfer_with_invalid_trip_and_route",
    ),
    (
        "big_gap_in_service",
        "future_calendar",
        "feed_valid_beyond_total_service_window",
        "service_window_outside_feed_period",
        "service_extends_far_in_the_future",
    ),
    (
        "stop_time_with_only_arrival_or_departure_time",
        "stop_time_with_arrival_before_previous_departure_time",
    ),
    (
        "missing_required_field",
        "translation_unexpected_value",
        "translation_foreign_key_violation",
        "translation_unknown_table_name",
    ),
    (
        "feed_info_lang_and_agency_lang_mismatch",
        "inconsistent_agency_lang",
        "inconsistent_agency_timezone",
        "missing_required_agency_id",
        "missing_recommended_field",
    ),
    (
        "pathway_to_stop_with_access_outside_of_station_pathways",
        "pathway_dangling_generic_node",
        "pathway_to_wrong_location_type",
        "pathway_to_platform_with_boarding_areas",
        "pathway_unreachable_location",
    ),
)


# The keyed reads the rules make on any real feed, pre-indexed by the main process
# before the pool spawns: a worker's connection is read-only, so its create_index is
# a no-op, and an unhinted column costs a scan rather than an error. Keep this list
# in step with the columns rules seek on; the determinism gate stays correct either
# way, only speed moves.
HOT_INDEXES = (
    ("stop_times.txt", "trip_id"),
    ("shapes.txt", "shape_id"),
    ("trips.txt", "trip_id"),
    ("trips.txt", "shape_id"),
    ("trips.txt", "route_id"),
    ("trips.txt", "service_id"),
    ("trips.txt", "block_id"),
    ("stops.txt", "stop_id"),
    ("stops.txt", "parent_station"),
    ("stops.txt", "zone_id"),
)


def cohort_parts(codes: list[str], workers: int) -> list[list[str]]:
    """Partition file-rule codes with each cache cohort kept whole.

    Cohorts first (largest first), then singleton codes, dealt round-robin over the
    parts. Every registered code lands in exactly one part; a cohort member that is
    not registered is simply skipped, so the map cannot strand a future rename.
    """
    registered = set(codes)
    grouped: list[list[str]] = []
    claimed: set[str] = set()
    for cohort in CACHE_COHORTS:
        members = [code for code in cohort if code in registered]
        if members:
            grouped.append(members)
            claimed.update(members)
    grouped.extend([code] for code in codes if code not in claimed)
    grouped.sort(key=len, reverse=True)
    parts: list[list[str]] = [[] for _ in range(min(workers, len(grouped)) or 1)]
    for position, group in enumerate(grouped):
        parts[position % len(parts)].extend(group)
    return [part for part in parts if part]


def round_robin(items: list, workers: int) -> list[list]:
    parts: list[list] = [[] for _ in range(min(workers, len(items)) or 1)]
    for position, item in enumerate(items):
        parts[position % len(parts)].append(item)
    return [part for part in parts if part]
