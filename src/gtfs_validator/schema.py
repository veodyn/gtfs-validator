"""The declarative table registry, loaded from generated upstream data.

Pure declaration: no parsing and no notice construction live here. The file and
column constants the container walk uses derive from this registry so that a
schema refresh cannot leave them stale.

REQUIRED_FILES is narrower than intuition expects. Upstream marks only
agency/routes/stop_times/trips as @Required at table level; stops.txt and
feed_info.txt are @ConditionallyRequired and their notices come from the rule
layer (MissingStopsFileValidator, MissingFeedInfoValidator). See container.py.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from importlib.resources import files

from gtfs_validator.columncap import DEFAULT_MAX_CHARS_PER_COLUMN


class Presence(Enum):
    REQUIRED = "REQUIRED"
    RECOMMENDED = "RECOMMENDED"
    CONDITIONALLY_REQUIRED = "CONDITIONALLY_REQUIRED"
    OPTIONAL = "OPTIONAL"


class FieldType(Enum):
    TEXT = "TEXT"
    ID = "ID"
    URL = "URL"
    EMAIL = "EMAIL"
    PHONE_NUMBER = "PHONE_NUMBER"
    COLOR = "COLOR"
    DATE = "DATE"
    TIME = "TIME"
    TIMEZONE = "TIMEZONE"
    CURRENCY_CODE = "CURRENCY_CODE"
    CURRENCY_AMOUNT = "CURRENCY_AMOUNT"
    LANGUAGE_CODE = "LANGUAGE_CODE"
    LATITUDE = "LATITUDE"
    LONGITUDE = "LONGITUDE"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    DECIMAL = "DECIMAL"
    ENUM = "ENUM"


@dataclass(frozen=True, slots=True)
class FieldReference:
    """A field's @ForeignKey target, and the upstream validator that checks it.

    The validator name is carried because foreign_key_violation's samples come out in ascending
    upstream class name, and that name cannot be derived from the filename: it singularises
    irregularly, frequencies.txt being GtfsFrequency.
    """

    table: str
    field: str
    validator: str


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    type: FieldType
    presence: Presence
    references: FieldReference | None = None
    bounds: str | None = None
    enum_values: tuple[int, ...] | None = None
    # Value to upstream's constant name, for the notices that report an enum by
    # name rather than by number.
    enum_names: Mapping[int, str] | None = None
    mixed_case: bool = False
    end_range: tuple[str, bool] | None = None
    default: str | None = None
    currency_field: str | None = None
    required_column: bool = False
    indexed: bool = False


@dataclass(frozen=True, slots=True)
class TableSchema:
    filename: str
    presence: Presence
    primary_key: tuple[str, ...]
    fields: tuple[Field, ...]
    # Parallel to primary_key: which translations.txt id each key column matches against.
    # byTranslationKey is generated from these upstream, so they are generated here too.
    primary_key_translation_types: tuple[str, ...] = ()
    # univocity's per-column character cap; -1 is unlimited. Only areas.txt overrides it.
    max_chars_per_column: int = DEFAULT_MAX_CHARS_PER_COLUMN
    single_row: bool = False

    def field(self, name: str) -> Field | None:
        for field in self.fields:
            if field.name == name:
                return field
        return None

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def names_with(self, presence: Presence) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.presence is presence)


def _build_field(raw: dict) -> Field:
    end_range = raw.get("end_range")
    references = raw.get("references")
    return Field(
        name=raw["name"],
        type=FieldType(raw["type"]),
        presence=Presence(raw["presence"]),
        references=FieldReference(**references) if references else None,
        bounds=raw.get("bounds"),
        enum_values=tuple(int(value) for value in raw["enum_values"])
        if "enum_values" in raw
        else None,
        enum_names={int(value): name for value, name in raw["enum_values"].items()}
        if "enum_values" in raw
        else None,
        mixed_case=raw.get("mixed_case", False),
        end_range=(end_range["field"], end_range["allow_equal"]) if end_range else None,
        default=raw.get("default"),
        currency_field=raw.get("currency_field"),
        required_column=raw.get("required_column", False),
        indexed=raw.get("indexed", False),
    )


@lru_cache(maxsize=1)
def _raw_schemas() -> dict:
    return json.loads(files("gtfs_validator.data").joinpath("table_schemas.json").read_text())


@lru_cache(maxsize=1)
def load_schemas() -> dict[str, TableSchema]:
    raw = _raw_schemas()
    return {
        filename: TableSchema(
            filename=filename,
            presence=Presence(table["presence"]),
            primary_key=tuple(table["primary_key"]),
            fields=tuple(_build_field(f) for f in table["fields"]),
            primary_key_translation_types=tuple(table.get("primary_key_translation_types", ())),
            max_chars_per_column=table.get("max_chars_per_column", DEFAULT_MAX_CHARS_PER_COLUMN),
            single_row=table.get("single_row", False),
        )
        for filename, table in raw["tables"].items()
    }


def _files_with(presence: Presence) -> frozenset[str]:
    return frozenset(name for name, schema in load_schemas().items() if schema.presence is presence)


REQUIRED_FILES = _files_with(Presence.REQUIRED)
RECOMMENDED_FILES = _files_with(Presence.RECOMMENDED)
KNOWN_FILES = frozenset(load_schemas())
# `GtfsFiles`, upstream's *other* list of table names. It is hand-maintained and
# has fallen eight names behind the descriptors it duplicates: no GTFS-Flex table
# and none of networks/route_networks/timeframes/rider_categories are in it. Its
# only caller is containsGtfsFileInSubfolder, so those eight are exactly the
# filenames a nested copy of which draws no invalid_input_files_in_subfolder from
# the jar. Using KNOWN_FILES there made us stricter than upstream on all eight.
GTFS_FILES_ENUM = frozenset(_raw_schemas()["gtfs_files_enum"])
SINGLE_ROW_FILES = frozenset(name for name, schema in load_schemas().items() if schema.single_row)


def unrecognized_value(field: Field) -> int | None:
    """The number EnumGenerator gives an enum's UNRECOGNIZED constant.

    `getMinUnrecognizedValue` initialises its accumulator to **zero** and then
    takes the minimum against each declared value, so the result is
    `min(0, *values) - 1` rather than `min(values) - 1`. For every GTFS enum,
    whose values are all non-negative, that is -1: an out-of-enum
    `exception_type` folds to -1 even though the enum starts at 1. An earlier
    reading of this dropped the zero and produced 0 for such enums.
    """
    if not field.enum_values:
        return None
    return min(0, *field.enum_values) - 1
