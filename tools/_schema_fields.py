"""Field-level parsing for `sync_upstream_schemas`: one Java accessor to one JSON field.

Split out when the generator passed the file-size limit. The division is by scope: this module knows
how to read the annotations attached to a single accessor, and nothing about tables, files or the
manifest it all ends up in. `sync_upstream_schemas` keeps the table-level parsing and the CLI.
"""

from __future__ import annotations

import re
from pathlib import Path

ANNOTATION_RE = re.compile(r"@(\w+)(?:\(([^)]*)\))?")
FOREIGN_KEY_RE = re.compile(r'table\s*=\s*"([^"]+)"\s*,\s*field\s*=\s*"([^"]+)"')
END_RANGE_RE = re.compile(r'field\s*=\s*"([^"]+)"(?:\s*,\s*allowEqual\s*=\s*(true|false))?')
DEFAULT_VALUE_RE = re.compile(r'"([^"]*)"')
# The name is captured alongside the value because notices report the enum by
# name, not by number: missing_stop_name carries locationType "STOP", not 0.
ENUM_MEMBER_RE = re.compile(r'@GtfsEnumValue\(\s*name\s*=\s*"([^"]+)"\s*,\s*value\s*=\s*(-?\d+)')

# Return type -> our FieldType, used when no explicit @FieldType is present.
TYPE_BY_RETURN = {
    "String": "TEXT",
    "int": "INTEGER",
    "long": "INTEGER",
    "double": "FLOAT",
    "float": "FLOAT",
    "BigDecimal": "DECIMAL",
    "GtfsTime": "TIME",
    "GtfsDate": "DATE",
    "GtfsColor": "COLOR",
    "Currency": "CURRENCY_CODE",
    "Locale": "LANGUAGE_CODE",
    "ZoneId": "TIMEZONE",
}
# Explicit @FieldType(FieldTypeEnum.X) -> our FieldType.
TYPE_BY_ANNOTATION = {
    "ID": "ID",
    "URL": "URL",
    "EMAIL": "EMAIL",
    "PHONE_NUMBER": "PHONE_NUMBER",
    "LATITUDE": "LATITUDE",
    "LONGITUDE": "LONGITUDE",
    "TIMEZONE": "TIMEZONE",
    "COLOR": "COLOR",
    "CURRENCY_CODE": "CURRENCY_CODE",
    "DATE": "DATE",
    "TIME": "TIME",
    "LANGUAGE_CODE": "LANGUAGE_CODE",
    "TEXT": "TEXT",
}
BOUND_BY_ANNOTATION = {
    "NonNegative": "NON_NEGATIVE",
    "Positive": "POSITIVE",
    "NonZero": "NON_ZERO",
}


# A string literal, or a line comment. Matching both in one pass is what makes the comment stripper
# string-aware: the alternation reaches a literal first, so a `//` inside one is never a comment.
_LITERAL_OR_COMMENT_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"|//[^\n]*')


def strip_line_comments(text: str) -> str:
    """Remove `//` comments, leaving `//` inside Java string literals alone.

    A commented-out annotation is not an annotation: GtfsLocationGroupStopsSchema keeps two
    `//  @ForeignKey(...)` lines, and reading them as live gave us two references upstream does not
    check, measured on probe `fkv10`.

    Naively deleting every `//...` also truncates a URL inside an annotation argument, so
    `@DefaultValue("https://example.test")` would lose its value while `MEMBER_RE` still found the
    accessor: the field would silently arrive with no default. No schema at the current pin has one,
    so this is a pin-refresh hazard rather than an observed corruption, which is exactly the kind
    that a regeneration would carry in quietly.
    """
    return _LITERAL_OR_COMMENT_RE.sub(
        lambda found: found.group(0) if found.group(0).startswith('"') else "", text
    )


def to_column(method_name: str) -> str:
    """tripId -> trip_id, matching upstream FieldNameConverter.gtfsColumnName."""
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", method_name).lower()


def parse_annotations(blob: str) -> dict[str, str | None]:
    return dict(ANNOTATION_RE.findall(blob or ""))


def enum_values(root: Path, type_name: str, cache: dict) -> dict[str, str] | None:
    """Read the permitted values of an enum column, keyed by value.

    A schema method returns GtfsRouteType, but the values are declared on a
    separate interface named GtfsRouteTypeEnum, as repeated
    @GtfsEnumValue(name = "BUS", value = 3) annotations. Values are not
    contiguous: route types skip 8 through 10.

    Both halves are kept. The value set drives unexpected_enum_value, and the
    name is what a notice reports: missing_stop_name carries locationType
    "STOP" rather than 0. JSON object keys are strings, so the value is the
    key in string form and the schema loader converts it back.
    """
    if type_name in cache:
        return cache[type_name]
    found = None
    for path in root.rglob(f"{type_name}Enum.java"):
        if "/test/" in str(path):
            continue
        members = ENUM_MEMBER_RE.findall(path.read_text(errors="replace"))
        if members:
            found = {
                str(int(value)): name for name, value in sorted(members, key=lambda m: int(m[1]))
            }
            break
    cache[type_name] = found
    return found


def _presence_of(annotations: dict) -> str:
    if "Required" in annotations:
        return "REQUIRED"
    if "ConditionallyRequired" in annotations:
        return "CONDITIONALLY_REQUIRED"
    if "Recommended" in annotations:
        return "RECOMMENDED"
    return "OPTIONAL"


def _resolve_type(
    return_type: str, annotations: dict, root: Path, cache: dict
) -> tuple[str, list[int] | None]:
    """Explicit @FieldType wins; otherwise infer from the Java return type."""
    field_type = TYPE_BY_RETURN.get(return_type, "ENUM")
    if "FieldType" in annotations:
        token = (annotations["FieldType"] or "").split(".")[-1]
        field_type = TYPE_BY_ANNOTATION.get(token, field_type)
    if "CurrencyAmount" in annotations:
        return "CURRENCY_AMOUNT", None
    if field_type != "ENUM":
        return field_type, None
    values = enum_values(root, return_type, cache)
    # An unresolvable enum type is a plain string upstream, not a failure.
    return ("ENUM", values) if values is not None else ("TEXT", None)


def _apply_flags(field: dict, annotations: dict) -> None:
    for annotation, key in (
        ("RequiredColumn", "required_column"),
        ("MixedCase", "mixed_case"),
        ("Index", "indexed"),
    ):
        if annotation in annotations:
            field[key] = True
    for bound, label in BOUND_BY_ANNOTATION.items():
        if bound in annotations:
            field["bounds"] = label


def validator_name(class_name: str, method: str) -> str:
    """`ForeignKeyValidatorGenerator.validatorName`: child class, capitalised accessor, suffix.

    The samples within foreign_key_violation come out in ascending simple class name, so this string
    is what the rule sorts on. Built here rather than derived from the filename because the class
    name singularises irregularly: frequencies.txt is GtfsFrequency.
    """
    return f"{class_name}{method[:1].upper()}{method[1:]}ForeignKeyValidator"


def _apply_references(field: dict, annotations: dict, class_name: str, method: str) -> None:
    if "CurrencyAmount" in annotations:
        # @CurrencyAmount(currencyField = "currency"): pull the quoted value out
        # rather than stripping quotes off the whole `currencyField = "currency"`
        # argument string.
        found = DEFAULT_VALUE_RE.search(annotations["CurrencyAmount"] or "")
        if found:
            field["currency_field"] = found.group(1)
    if "DefaultValue" in annotations:
        found = DEFAULT_VALUE_RE.search(annotations["DefaultValue"] or "")
        if found:
            field["default"] = found.group(1)
    if "ForeignKey" in annotations:
        found = FOREIGN_KEY_RE.search(annotations["ForeignKey"] or "")
        if found:
            field["references"] = {
                "table": found.group(1),
                "field": found.group(2),
                "validator": validator_name(class_name, method),
            }
    if "EndRange" in annotations:
        found = END_RANGE_RE.search(annotations["EndRange"] or "")
        if found:
            field["end_range"] = {
                "field": found.group(1),
                "allow_equal": found.group(2) == "true",
            }


def build_field(
    column: str,
    return_type: str,
    annotations: dict,
    root: Path,
    cache: dict,
    class_name: str,
    method: str,
) -> dict:
    field_type, values = _resolve_type(return_type, annotations, root, cache)
    field: dict = {"name": column, "type": field_type}
    if values is not None:
        field["enum_values"] = values
    field["presence"] = _presence_of(annotations)
    _apply_flags(field, annotations)
    _apply_references(field, annotations, class_name, method)
    return field
