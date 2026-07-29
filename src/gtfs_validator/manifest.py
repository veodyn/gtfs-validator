"""Loads the generated canonical notice manifest.

IMPLEMENTED is the registry of codes this build can emit. It grows plan by plan
and is asserted against the manifest so a typo or a severity drift fails CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from gtfs_validator.notices import Severity

# Stage 1 (container) and stage 2 (parse). Later plans extend this set.
IMPLEMENTED: set[str] = {
    "missing_required_file",
    "missing_recommended_file",
    "unknown_file",
    "empty_file",
    "invalid_input_files_in_subfolder",
    "too_many_rows",
    "csv_parsing_failed",
    "empty_row",
    "duplicated_column",
    "empty_column_name",
    "invalid_row_length",
    "unknown_column",
    "missing_required_column",
    "missing_recommended_column",
    "inconsistent_agency_lang",
    "inconsistent_agency_timezone",
    "missing_required_agency_id",
    "station_with_parent_station",
    "platform_without_parent_station",
    "location_without_parent_station",
    "invalid_geometry",
    "stop_time_with_only_arrival_or_departure_time",
    "stop_time_with_arrival_before_previous_departure_time",
    "stop_access_specified_for_stop_with_no_parent_station",
    "stop_access_specified_for_incorrect_location",
    "transfer_with_suspicious_mid_trip_in_seat",
    "inconsistent_route_type_for_in_seat_transfer",
    "forbidden_continuous_pickup_drop_off",
    "feed_info_lang_and_agency_lang_mismatch",
    "fare_product_with_multiple_default_rider_categories",
    "duplicate_geography_id",
    "inconsistent_route_type_for_block_id",
    "trip_with_shape_dist_traveled_but_no_shape_distances",
    "transfer_with_invalid_stop_location_type",
    "missing_pickup_drop_off_booking_rule_id",
    "translation_unknown_table_name",
    "translation_unexpected_value",
    "translation_foreign_key_violation",
    "unused_trip",
    "unsorted_stop_times",
    "stop_without_stop_time",
    "location_with_unexpected_stop_time",
    "pathway_dangling_generic_node",
    "pathway_to_platform_with_boarding_areas",
    "pathway_to_stop_with_access_outside_of_station_pathways",
    "pathway_to_wrong_location_type",
    "forbidden_prior_day_booking_field_value",
    "forbidden_prior_notice_start_day",
    "forbidden_prior_notice_start_time",
    "forbidden_real_time_booking_field_value",
    "forbidden_same_day_booking_field_value",
    "invalid_prior_notice_duration_min",
    "missing_prior_notice_duration_min",
    "missing_prior_notice_last_day",
    "missing_prior_notice_last_time",
    "missing_prior_notice_start_time",
    "prior_notice_last_day_after_start_day",
    "leading_or_trailing_whitespaces",
    "new_line_in_value",
    # Stage 3 (field typing), added in plan 2.
    "invalid_color",
    "invalid_currency",
    "invalid_currency_amount",
    "invalid_date",
    "invalid_email",
    "invalid_float",
    "invalid_integer",
    "invalid_language_code",
    "invalid_phone_number",
    "invalid_time",
    "invalid_timezone",
    "invalid_url",
    "invalid_character",
    "non_ascii_or_non_printable_char",
    "number_out_of_range",
    "unexpected_enum_value",
    "missing_required_field",
    "missing_recommended_field",
    "mixed_case_recommended_field",
    "start_and_end_range_equal",
    "start_and_end_range_out_of_order",
    # Stage 4 (indexing), added in plan 2.
    "duplicate_key",
    "more_than_one_entity",
    # Stage 5 (rules), added in plan 3.
    "route_both_short_and_long_name_missing",
    "route_short_name_too_long",
    "route_long_name_contains_short_name",
    "same_name_and_description_for_route",
    "route_color_contrast",
    "missing_stop_name",
    "same_name_and_description_for_stop",
    "attribution_without_role",
    "bidirectional_exit_gate",
    "missing_feed_contact_email_and_url",
    "timeframe_only_start_or_end_time_specified",
    "timeframe_start_or_end_time_greater_than_twenty_four_hours",
    "fare_transfer_rule_duration_limit_without_type",
    "fare_transfer_rule_duration_limit_type_without_duration_limit",
    # Stage 5, the date cohort, added in plan 4.
    "missing_feed_info_date",
    "feed_expiration_date7_days",
    "feed_expiration_date30_days",
    "future_feed",
    "service_has_no_active_day_of_the_week",
    "missing_calendar_and_calendar_date_files",
    "expired_calendar",
    # Stage 5, the service-window cohort, added in plan 5.
    "future_calendar",
    "service_window_outside_feed_period",
    "feed_valid_beyond_total_service_window",
    "big_gap_in_service",
    "service_extends_far_in_the_future",
    "trip_coverage_not_active_for_next7_days",
    # Stage 6 (GeoJSON), added in plan 6. invalid_geometry is registered above rather
    # than here, next to the rules added after the plans: it reports JTS IsValidOp's own
    # wording, so its message table is generated from the pinned jar.
    "malformed_json",
    # Emitted by table/GtfsGeoJsonFeaturesContainer while it builds its id map, not by any
    # validator, so it lives in geojson.parse rather than in a rule module. Not to be confused with
    # geo_json_duplicated_element below, which is a repeated *JSON object key*.
    "duplicate_geo_json_key",
    "geo_json_duplicated_element",
    "geo_json_unknown_element",
    "unsupported_geo_json_type",
    "missing_required_element",
    "unsupported_feature_type",
    "unsupported_geometry_type",
    # Stage 5, added after plan 6.
    "missing_bike_allowance",
    "route_networks_specified_in_more_than_one_file",
    "duplicate_fare_media",
    "single_shape_point",
    "unused_shape",
    "unused_station",
    "unusable_trip",
    "pathway_loop",
    "stop_without_location",
    "missing_level_id",
    "missing_trip_edge",
    "forbidden_shape_dist_traveled",
    "forbidden_geography_id",
    "missing_timepoint_value",
    "stop_time_timepoint_without_times",
    "forbidden_pickup_type",
    "forbidden_drop_off_type",
    "fare_transfer_rule_invalid_transfer_count",
    "fare_transfer_rule_without_transfer_count",
    "fare_transfer_rule_with_forbidden_transfer_count",
    # 44 validators generated from @ForeignKey, plus five hand-written ones, all one code.
    "foreign_key_violation",
    # StopZoneIdValidator.
    "stop_without_zone_id",
    # DuplicateRouteNameValidator.
    "duplicate_route_name",
    # TransfersTripReferenceValidator, two independent questions per transfer end.
    "transfer_with_invalid_trip_and_route",
    "transfer_with_invalid_trip_and_stop",
    # GeoJsonFileLoader.validateCoordinates, alongside the stage 6 codes above.
    "point_near_origin",
    "point_near_pole",
    # TripAndShapeDistanceValidator, one comparison per trip against its shape.
    "trip_distance_exceeds_shape_distance",
    "trip_distance_exceeds_shape_distance_below_threshold",
    # ParentStationValidator, whose other code is unused_station above.
    "wrong_parent_location_type",
    # TransferDistanceValidator, one pass over transfers.txt against the stop tree.
    "transfer_distance_above_2_km",
    "transfer_distance_too_large",
    # UrlConsistencyValidator, one validator over agency.txt, routes.txt and stops.txt.
    "same_route_and_agency_url",
    "same_stop_and_agency_url",
    "same_stop_and_route_url",
    # ShapeIncreasingDistanceValidator, one pass over each shape deciding four branches.
    "decreasing_shape_distance",
    "equal_shape_distance_same_coordinates",
    "equal_shape_distance_diff_coordinates",
    "equal_shape_distance_diff_coordinates_distance_below_threshold",
    # PickupDropOffWindowValidator, three independent questions about one row.
    "forbidden_arrival_or_departure_time",
    "missing_pickup_or_drop_off_window",
    "invalid_pickup_drop_off_window",
    # StopTimesRecordValidator, the whole-file half of the same flex columns.
    "missing_stop_times_record",
    # OverlappingFrequencyValidator and TimeframeOverlapValidator, one interval scan twice.
    "overlapping_frequency",
    "timeframe_overlap",
    # StopTimeIncreasingDistanceValidator.
    "decreasing_or_equal_stop_time_distance",
    # StopTimeTravelSpeedValidator, whose two scans share a grouping and little else.
    "fast_travel_between_consecutive_stops",
    "fast_travel_between_far_stops",
    # BlockTripsWithOverlappingStopTimesValidator.
    "block_trips_with_overlapping_stop_times",
    # OverlappingPickupDropOffZoneValidator, whose zone test is JTS's `overlaps`.
    "overlapping_zone_and_pickup_drop_off_window",
    # TripHeadsignValidator, which stops at the first circular trip. Upstream's bug, ported.
    "trip_headsign_matches_intermediate_stop",
    # PathwayReachableLocationValidator, two breadth-first searches over the pathway graph.
    "pathway_unreachable_location",
    # ShapeToStopMatchingValidator, one assignment search per trip producing four codes. The
    # too-far pair share a set of reported stop ids, so they are not independent.
    "stop_too_far_from_shape",
    "stop_too_far_from_shape_using_user_distance",
    "stop_has_too_many_matches_for_shape",
    "stops_match_shape_out_of_order",
}


# The rest of upstream's surface: codes no feed can reach through the jar either,
# so not implementing them is correct rather than outstanding. All three are in
# `main/.../deprecated/` and no code constructs them anywhere upstream, checked
# across every module rather than just `main`. A constructor that is never called
# is a compile-level proof of unreachability, stronger than any probe.
#
# Naming them here rather than only in prose is what lets
# test_manifest.py assert set equality against the manifest. Without it the test
# can only count, so a pin bump fails with "177 != 176" and says nothing about
# what arrived. With it, a new upstream code fails by name.
UNREACHABLE: dict[str, str] = {
    "fare_transfer_rule_missing_transfer_count": "deprecated upstream, never constructed",
    "missing_prior_day_booking_field_value": "deprecated upstream, never constructed",
    "unused_parent_station": "deprecated upstream, never constructed",
}


@dataclass(frozen=True)
class Manifest:
    codes: frozenset[str]
    notices: dict[str, dict]
    meta: dict

    def severity_of(self, code: str) -> Severity:
        return Severity[self.notices[code]["severity"]]

    def context_fields_of(self, code: str) -> dict[str, str]:
        return dict(self.notices[code]["context_fields"])


@lru_cache(maxsize=1)
def load_manifest() -> Manifest:
    raw = json.loads(files("gtfs_validator.data").joinpath("canonical_notices.json").read_text())
    notices = raw["notices"]
    return Manifest(frozenset(notices), notices, raw["_meta"])


def registered_codes() -> frozenset[str]:
    """Every code the rule registry can emit.

    Set equality against IMPLEMENTED proves registration, not implementation: a
    rule body of `return ()` satisfies it. The fixture requirement in each rule's
    test is the other half of that gate.
    """
    from gtfs_validator.rules.registry import load_rules

    return frozenset(load_rules())
