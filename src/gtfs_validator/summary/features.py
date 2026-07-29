"""`summary.gtfsFeatures`, ported from `FeedMetadata.loadSpecFeatures`.

Thirty-four features. Fourteen are decided by a file holding at least one row,
and twenty-three by a field being set on at least one row; three names appear in
both passes, which is where the one subtlety lives.

**Order and value come from different passes.** `specFeatures` upstream is a
`LinkedHashMap` whose key, `FeatureMetadata`, defines equality on the feature
*name* alone and ignores the group. The file pass inserts `Pathway Connections`,
`Pathway Signs` and `Pathway Details` first; the field pass then re-`put`s all
three. A `LinkedHashMap.put` on an existing key keeps the original position and
the original key object while taking the new value, and Python's dict does
exactly the same, so keying on a name-equal `Feature` reproduces it without a
special case. Get this wrong and the three appear at the end of `gtfsFeatures`
in the wrong order, which the byte comparison then reports.

Only features whose value is true reach the report.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from gtfs_validator.rules.feedview import FeedView
from gtfs_validator.summary.reads import any_record, any_record_with, has, table_rows

BASE_DOC_URL = "https://gtfs.org/getting_started/features/"


@dataclass(frozen=True)
class Feature:
    """`FeatureMetadata`. Equality is on the name alone, as upstream's is.

    The group still matters, because it builds the documentation anchor, but it
    is deliberately outside `__eq__` so that a name re-inserted by the second
    pass lands on the first pass's entry.
    """

    name: str
    group: str | None = field(default=None, compare=False)

    @property
    def doc_url(self) -> str:
        """`getDocUrl()`: the group lowercased with underscores, the name with hyphens."""
        group = (self.group or "base_add-ons").lower().replace(" ", "_")
        return f"{BASE_DOC_URL}{group}/#{self.name.lower().replace(' ', '-')}"


# `FILE_BASED_FEATURES`, in upstream's declaration order. Three of these names
# are decided again by the field pass; they keep these positions.
FILE_BASED: tuple[tuple[str, str | None, str], ...] = (
    ("Pathway Connections", "Pathways", "pathways.txt"),
    ("Pathway Signs", "Pathways", "pathways.txt"),
    ("Pathway Details", "Pathways", "pathways.txt"),
    ("Levels", "Pathways", "levels.txt"),
    ("Transfers", None, "transfers.txt"),
    ("Shapes", None, "shapes.txt"),
    ("Frequencies", None, "frequencies.txt"),
    ("Feed Information", None, "feed_info.txt"),
    ("Attributions", None, "attributions.txt"),
    ("Translations", None, "translations.txt"),
    ("Fares V1", "Fares", "fare_attributes.txt"),
    ("Fare Products", "Fares", "fare_products.txt"),
    ("Fare Transfers", "Fares", "fare_transfer_rules.txt"),
    ("Booking Rules", "Flexible Services", "booking_rules.txt"),
)


def _any_of(*sources: tuple[str, tuple[str, ...]]) -> Callable[[FeedView], bool]:
    """A predicate that is true when any one source matches.

    Each source is a table and the fields one of its rows must *all* set, which
    is upstream's `hasAtLeastOneRecordForFields`. Every upstream caller passes a
    single condition and ORs whole calls together, so an OR across sources and an
    AND within one is the shape that actually occurs.
    """

    def check(view: FeedView) -> bool:
        return any(any_record_with(view, name, *fields) for name, fields in sources)

    return check


def _trip_with_only(column: str) -> Callable[[FeedView], bool]:
    """One stop_time carrying trip_id and this column, and no stop_id."""

    def check(view: FeedView) -> bool:
        return any(
            has(row, "trip_id") and has(row, column) and not has(row, "stop_id")
            for row in table_rows(view, "stop_times.txt")
        )

    return check


def _deviated_fixed_route(view: FeedView) -> bool:
    """`hasAtLeastOneTripWithAllFields`: one trip whose stop_times cover all five fields.

    The fields accumulate *across* a trip's rows rather than having to appear on
    one of them, so this cannot be an `any_record_with`. Upstream walks
    `byTripIdMap`, which it has already built; we stream stop_times.txt once and
    keep a bitmask per trip instead, so the memory is bounded by the trip count
    rather than by the row count. A 13M-row stop_times.txt is the case that makes
    the difference, and the differential cannot see it because every probe feed
    is tiny.
    """
    wanted = 0b11111
    seen: dict[object, int] = {}
    for row in table_rows(view, "stop_times.txt"):
        trip = row.get("trip_id")
        mask = seen.get(trip, 0)
        mask |= (
            (0b00001 if has(row, "trip_id") else 0)
            | (0b00010 if has(row, "location_id") else 0)
            | (0b00100 if has(row, "stop_id") else 0)
            | (0b01000 if has(row, "arrival_time") else 0)
            | (0b10000 if has(row, "departure_time") else 0)
        )
        if mask == wanted:
            return True
        seen[trip] = mask
    return False


def _route_based_fares(view: FeedView) -> bool:
    return (
        any_record_with(view, "routes.txt", "network_id") or any_record(view, "networks.txt")
    ) and (
        any_record(view, "fare_products.txt")
        and any_record(view, "fare_leg_rules.txt")
        and any_record_with(view, "fare_leg_rules.txt", "network_id")
    )


def _leg_rule_pair(first: str, second: str) -> Callable[[FeedView], bool]:
    """Zone- and time-based fares: both share this shape, differing only in the pair."""

    def check(view: FeedView, gate: str) -> bool:
        return (
            any_record(view, gate)
            and any_record(view, "fare_products.txt")
            and any_record(view, "fare_leg_rules.txt")
            and (
                any_record_with(view, "fare_leg_rules.txt", first)
                or any_record_with(view, "fare_leg_rules.txt", second)
            )
        )

    gate = "areas.txt" if first == "from_area_id" else "timeframes.txt"
    return lambda view: check(view, gate)


def _product_reference(gate: str, column: str) -> Callable[[FeedView], bool]:
    """Fare Media and Rider Categories: a gate file, fare_products, and the reference.

    Upstream returns early with false when either file is empty rather than
    falling through, which reads as belt and braces and is: the field cannot be
    set on a row of a table with no rows. Kept because the shape is upstream's.
    """

    def check(view: FeedView) -> bool:
        if not any_record(view, gate) or not any_record(view, "fare_products.txt"):
            return False
        return any_record_with(view, "fare_products.txt", column)

    return check


def _fixed_stops_drt(view: FeedView) -> bool:
    return any_record(view, "location_groups.txt") and _trip_with_only("location_group_id")(view)


# `loadSpecFeaturesBasedOnFieldPresence`, in call order. The order decides where
# a name that the file pass did not already place ends up in `gtfsFeatures`.
FIELD_BASED: tuple[tuple[str, str | None, Callable[[FeedView], bool]], ...] = (
    (
        "Route Colors",
        None,
        _any_of(("routes.txt", ("route_color",)), ("routes.txt", ("route_text_color",))),
    ),
    (
        "Headsigns",
        None,
        _any_of(("trips.txt", ("trip_headsign",)), ("stop_times.txt", ("stop_headsign",))),
    ),
    (
        "Stops Wheelchair Accessibility",
        "Accessibility",
        _any_of(("stops.txt", ("wheelchair_boarding",))),
    ),
    (
        "Trips Wheelchair Accessibility",
        "Accessibility",
        _any_of(("trips.txt", ("wheelchair_accessible",))),
    ),
    ("Text-to-Speech", "Accessibility", _any_of(("stops.txt", ("tts_stop_name",)))),
    ("Bike Allowed", None, _any_of(("trips.txt", ("bikes_allowed",)))),
    ("Location Types", None, _any_of(("stops.txt", ("location_type",)))),
    ("Stop Access", None, _any_of(("stops.txt", ("stop_access",)))),
    ("In-station Traversal Time", "Pathways", _any_of(("pathways.txt", ("traversal_time",)))),
    (
        "Pathway Signs",
        "Pathways",
        _any_of(
            ("pathways.txt", ("signposted_as",)), ("pathways.txt", ("reversed_signposted_as",))
        ),
    ),
    (
        "Pathway Details",
        "Pathways",
        _any_of(
            ("pathways.txt", ("max_slope",)),
            ("pathways.txt", ("min_width",)),
            ("pathways.txt", ("length",)),
            ("pathways.txt", ("stair_count",)),
        ),
    ),
    ("Pathway Connections", "Pathways", lambda view: any_record(view, "pathways.txt")),
    ("Route-Based Fares", "Fares", _route_based_fares),
    (
        "Continuous Stops",
        "Flexible Services",
        _any_of(
            ("routes.txt", ("continuous_drop_off",)),
            ("routes.txt", ("continuous_pickup",)),
            ("stop_times.txt", ("continuous_drop_off",)),
            ("stop_times.txt", ("continuous_pickup",)),
        ),
    ),
    ("Zone-Based Demand Responsive Services", "Flexible Services", _trip_with_only("location_id")),
    ("Predefined Routes with Deviation", "Flexible Services", _deviated_fixed_route),
    ("Fare Media", "Fares", _product_reference("fare_media.txt", "fare_media_id")),
    ("Rider Categories", "Fares", _product_reference("rider_categories.txt", "rider_category_id")),
    (
        "Time-Based Fares",
        "Fares",
        _leg_rule_pair("from_timeframe_group_id", "to_timeframe_group_id"),
    ),
    ("Zone-Based Fares", "Fares", _leg_rule_pair("from_area_id", "to_area_id")),
    (
        "Contactless EMV Support",
        "Fares",
        _any_of(("agency.txt", ("cemv_support",)), ("routes.txt", ("cemv_support",))),
    ),
    ("Fixed-Stops Demand Responsive Transit", "Flexible Services", _fixed_stops_drt),
    ("Cars Allowed", None, _any_of(("trips.txt", ("cars_allowed",)))),
)


def detect(view: FeedView) -> dict[Feature, bool]:
    """Every feature and whether the feed has it, in upstream's map order."""
    found: dict[Feature, bool] = {}
    for name, group, filename in FILE_BASED:
        found[Feature(name, group)] = any_record(view, filename)
    for name, group, predicate in FIELD_BASED:
        found[Feature(name, group)] = predicate(view)
    return found


def present(view: FeedView) -> list[Feature]:
    """Only the features the feed has. `gtfsFeatures` carries no others."""
    return [feature for feature, found in detect(view).items() if found]
