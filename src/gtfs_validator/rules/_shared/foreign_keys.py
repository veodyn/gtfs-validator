"""The references upstream checks, in the order it reports them.

There is no single foreign key validator upstream. `ForeignKeyValidatorGenerator` emits one
FileValidator per @ForeignKey-annotated field, 44 of them at the pin, and five more are hand-written
for references the annotation cannot express: a key that may live in either of two files, and one
that lives in locations.geojson. All construct the same notice, and our registry allows one module
per code, so the port is this list plus one loop.

**The order is ascending upstream simple class name**, which is a property of ClassGraph's scan
order rather than a documented contract: `ValidatorLoader` keeps `multiFileValidators` in scan order,
and `NoticeContainer` groups with `treeKeys().arrayListValues()`, so values keep insertion order.
Sorting by (child file, child field) instead reproduces most of it and fails on the hand-written
classes, whose names follow no such pattern: probe `fkv28` reports fare_leg_join_rules before
attributions, and `fkv29` reports trips before stop_times, both the reverse of filename order.
Re-measure this if the pin moves.
"""

from __future__ import annotations

from dataclasses import dataclass

from gtfs_validator.schema import load_schemas


@dataclass(frozen=True)
class Parent:
    """One table and column a key may be found in, and how that lookup treats an absent key.

    `defaults_empty` is upstream's two branches, and the difference is observable. A generated
    validator looks the key up as `byKey(k).isPresent()` when the parent field is the parent's
    single-column primary key, and as `!byKey(k).isEmpty()` when it is merely `@Index`. The index is
    built from the getter with no presence guard, so a parent row whose key is absent is indexed
    under `""` and an empty child key resolves against it. The primary key map does not behave that
    way.

    Measured on two probes that disagree:

    - `fkv31`: fare_rules.origin_id is `""` and no stop declares a zone_id. stops.zone_id is
      `@Index`, and the jar is **silent**.
    - `fkv34`: routes.agency_id is `""` and the lone agency omits agency_id. agency.agency_id is a
      single-column primary key, and the jar **reports**.

    A uniform rule fails one or the other, which is why this is a field rather than a constant.
    """

    filename: str
    column: str
    defaults_empty: bool


@dataclass(frozen=True)
class Reference:
    child_file: str
    child_field: str
    # The parents whose union the key is looked up in. More than one only for the hand-written
    # checks; the generated shape always has exactly one.
    parents: tuple[Parent, ...]
    # What the notice prints, which for two parents is "a.txt or b.txt" rather than either name.
    parent_label: str
    parent_field: str
    # The upstream class simple name, and the sort key. See the module docstring.
    validator: str
    # Whether an empty child key is skipped as well as an absent one. Two of the hand-written
    # validators test `foreignKey.isEmpty()` where every generated one tests `!hasX()`, and the two
    # differ on a value that trims to nothing: `fkv30` reports an empty route_id with
    # `fieldValue: ""`, while `fkv32` and `fkv33` are silent on an empty network_id and location_id.
    skip_empty: bool = False


def _defaults_empty(schemas: dict, filename: str, column: str) -> bool:
    """Whether the lookup is by @Index rather than by single-column primary key.

    `ForeignKeyValidatorGenerator.generateValidator` picks its branch with exactly this test, so the
    condition is copied rather than reasoned about: primary key first, index otherwise. See `Parent`
    for the two probes that make the difference visible.
    """
    schema = schemas.get(filename)
    if schema is None:
        return False
    single_column_primary_key = len(schema.primary_key) == 1 and schema.primary_key[0] == column
    return not single_column_primary_key


def _generated() -> list[Reference]:
    """One reference per @ForeignKey field, read from the generated schema data."""
    schemas = load_schemas()
    found = []
    for filename, schema in schemas.items():
        for field in schema.fields:
            reference = field.references
            if reference is None:
                continue
            found.append(
                Reference(
                    child_file=filename,
                    child_field=field.name,
                    parents=(
                        Parent(
                            filename=reference.table,
                            column=reference.field,
                            defaults_empty=_defaults_empty(
                                schemas, reference.table, reference.field
                            ),
                        ),
                    ),
                    parent_label=reference.table,
                    parent_field=reference.field,
                    validator=reference.validator,
                )
            )
    return found


# The five validators upstream writes by hand, because @ForeignKey cannot name two parent files or a
# parent outside the .txt tables. Listed in the order each class checks its fields, which is what
# keeps from_network_id ahead of to_network_id under a stable sort.
# `defaults_empty` is per parent here, not per reference, because these validators mix the two
# lookups in one condition: `calendarContainer.byServiceId(k).isPresent()` is a primary key on a
# single-column key, while `calendarDateContainer.byServiceId(k).isEmpty()` is an index, since
# calendar_dates keys on (service_id, date). See `Parent`.
_CALENDARS = (
    Parent(filename="calendar.txt", column="service_id", defaults_empty=False),
    Parent(filename="calendar_dates.txt", column="service_id", defaults_empty=True),
)
_CALENDAR_LABEL = "calendar.txt or calendar_dates.txt"
# GtfsRoute.FILENAME + " or " + GtfsNetwork.FILENAME, so routes comes first in the label even where
# the lookup consults networks first. Measured on `fkv18`.
_NETWORK_LABEL = "routes.txt or networks.txt"
# networks.network_id is that table's primary key; routes.network_id is an @Index on a table keyed
# by route_id, so an absent routes.network_id is indexed under "".
_NETWORKS = (
    Parent(filename="networks.txt", column="network_id", defaults_empty=False),
    Parent(filename="routes.txt", column="network_id", defaults_empty=True),
)

HAND_WRITTEN = (
    Reference(
        child_file="fare_leg_join_rules.txt",
        child_field="from_network_id",
        parents=_NETWORKS,
        parent_label=_NETWORK_LABEL,
        parent_field="network_id",
        validator="FareLegJoinRuleValidator",
    ),
    Reference(
        child_file="fare_leg_join_rules.txt",
        child_field="to_network_id",
        parents=_NETWORKS,
        parent_label=_NETWORK_LABEL,
        parent_field="network_id",
        validator="FareLegJoinRuleValidator",
    ),
    Reference(
        child_file="fare_leg_rules.txt",
        child_field="network_id",
        parents=_NETWORKS,
        parent_label=_NETWORK_LABEL,
        parent_field="network_id",
        validator="GtfsFareLegRuleNetworkIdForeignKeyValidator",
        # `if (foreignKey.isEmpty()) continue;`, unlike the join rule pair above it, which tests
        # hasFromNetworkId(). Measured on `fkv32`, where an empty network_id draws nothing.
        skip_empty=True,
    ),
    # No presence guard upstream: GtfsTripServiceIdForeignKeyValidator reads serviceId() straight,
    # so an empty one would report fieldValue "". Unreachable, because service_id is required and an
    # empty one marks trips.txt UNPARSABLE_ROWS, which skips the validator outright. Measured on
    # `fkv5` and `fkv16`, so the guard is applied uniformly here rather than reproducing a branch no
    # feed can enter.
    Reference(
        child_file="trips.txt",
        child_field="service_id",
        parents=_CALENDARS,
        parent_label=_CALENDAR_LABEL,
        parent_field="service_id",
        validator="GtfsTripServiceIdForeignKeyValidator",
    ),
    # The column holding the feature ids is feature_id; the notice prints `id`, which is
    # GtfsGeoJsonFeature.FEATURE_ID_FIELD_NAME. Two different strings, both measured on `fkv20`.
    Reference(
        child_file="stop_times.txt",
        child_field="location_id",
        parents=(Parent(filename="locations.geojson", column="feature_id", defaults_empty=False),),
        parent_label="locations.geojson",
        parent_field="id",
        validator="LocationIdForeignKeyValidator",
        # `if (foreignKey.isEmpty()) continue;` again. Measured on `fkv33`.
        skip_empty=True,
    ),
    Reference(
        child_file="timeframes.txt",
        child_field="service_id",
        parents=_CALENDARS,
        parent_label=_CALENDAR_LABEL,
        parent_field="service_id",
        validator="TimeframeServiceIdForeignKeyValidator",
    ),
)

# Stable sort, which is what holds from_network_id ahead of to_network_id: both come from
# FareLegJoinRuleValidator and so share a sort key.
REFERENCES = tuple(sorted([*_generated(), *HAND_WRITTEN], key=lambda ref: ref.validator))


def references() -> tuple[Reference, ...]:
    """Every reference upstream checks, in the order upstream reports them.

    Built once at import. `load_schemas()` re-reads and re-parses the JSON on every call, and the
    rule asks for this list once per feed, so computing it per call would put a parse of the whole
    schema data inside the validation run for no gain.
    """
    return REFERENCES
