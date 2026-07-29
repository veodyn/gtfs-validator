"""Enum constant names for the notices that report a type by name."""

from __future__ import annotations

from gtfs_validator.schema import load_schemas

# The generated enum's own name for a value outside it. The store folds such values to
# UNRECOGNIZED_VALUE, and the constant is what a notice reports for them.
UNRECOGNIZED = "UNRECOGNIZED"
UNRECOGNIZED_VALUE = -1


def enum_name(filename: str, field_name: str, value: int) -> str | None:
    """The enum constant's name, which is what such a notice carries.

    Measured on missing_stop_name and stop_without_location: both report locationType as "STOP" or
    "STATION" rather than 0 or 1. The generated manifest types the field as `object`, or omits it, so
    the jar's output is the contract.

    A value outside the enum reports "UNRECOGNIZED", the generated constant's name, not the empty
    string. Every caller was spelling `enum_name(...) or ""`, which produced "" for exactly the
    values this is most likely to be asked about, so the fallback belongs here rather than at seven
    call sites.
    """
    field = load_schemas()[filename].field(field_name)
    if field is None or field.enum_names is None:
        return None
    if value == UNRECOGNIZED_VALUE and value not in field.enum_names:
        return UNRECOGNIZED
    return field.enum_names.get(value, UNRECOGNIZED if value is not None else None)
