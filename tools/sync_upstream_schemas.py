#!/usr/bin/env python3
"""Regenerate table_schemas.json from a pinned upstream checkout.

Usage:
    python tools/sync_upstream_schemas.py --checkout /path/to/upstream

Each upstream Gtfs*Schema.java is a Java interface whose methods are columns.
The field type comes from an explicit @FieldType annotation when present and
from the method's return type otherwise. Enum-typed columns become
FieldType.ENUM carrying their permitted values, read from the Gtfs*Enum source.

@GtfsJson marks GtfsGeoJsonFeatureSchema, which is not a CSV table. It is skipped
here and handled by plan 5, so this emits 31 tables from 32 schema files.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from _schema_fields import build_field, parse_annotations, strip_line_comments, to_column

OUT = Path(__file__).resolve().parents[1] / "src/gtfs_validator/data/table_schemas.json"

# Two spellings in the source: @GtfsTable("x.txt") and the keyword form
# @GtfsTable(value = "feed_info.txt", singleRow = true). Missing the second one
# silently drops feed_info.txt and loses the singleRow marker with it.
TABLE_RE = re.compile(r'@GtfsTable\(\s*(?:value\s*=\s*)?"([^"]+)"([^)]*)\)')
# A method declaration plus every annotation attached above it.
MEMBER_RE = re.compile(
    r"((?:[ \t]*@\w+(?:\([^)]*\))?[ \t]*\n?)*)[ \t]*([\w.<>]+)[ \t]+(\w+)\(\)[ \t]*;",
    re.M,
)


def _table_annotation(text: str) -> str:
    """Everything inside `@GtfsTable(...)`, with comments removed.

    `[^)]*` is not enough: areas.txt puts its `maxCharsPerColumn = -1` after a comment that
    itself contains `(-1)` and `(e.g. ...)`, so a non-greedy scan stopped inside the comment and
    the override was silently dropped. `single_row` was read the same way and was only correct
    because feed_info.txt happens to have no parenthesised comment. Strip the comments first,
    then take the balanced parenthesis.
    """
    start = text.index("@GtfsTable(") + len("@GtfsTable(")
    without_comments = re.sub(r"//[^\n]*", "", text[start:])
    depth = 1
    for index, character in enumerate(without_comments):
        depth += {"(": 1, ")": -1}.get(character, 0)
        if depth == 0:
            return without_comments[:index]
    return without_comments


def parse_schema(path: Path, root: Path, cache: dict) -> tuple[str, dict] | None:
    text = path.read_text(errors="replace")
    table = TABLE_RE.search(text)
    if not table or "interface" not in text:
        return None  # @GtfsJson: the GeoJSON schema, handled in plan 5.
    filename = table.group(1)
    annotation = _table_annotation(text)

    head, _, body = text.partition("public interface")
    # A commented-out annotation is not an annotation; see `strip_line_comments` for why this cannot
    # be a plain `//.*` substitution. `_table_annotation` strips comments for the same reason.
    body = strip_line_comments(body)
    # The child half of the generated validator's name, which is the schema interface without its
    # suffix: GtfsTripSchema.java -> GtfsTrip.
    class_name = re.sub(r"Schema$", "", path.stem)
    if "@Required" in head:
        presence = "REQUIRED"
    elif "@Recommended" in head:
        presence = "RECOMMENDED"
    else:
        presence = "OPTIONAL"

    fields, primary_key, translation_types = [], [], []
    for annotation_blob, return_type, method in MEMBER_RE.findall(body):
        annotations = parse_annotations(annotation_blob)
        column = to_column(method)
        field = build_field(
            column, return_type.split(".")[-1], annotations, root, cache, class_name, method
        )
        if "PrimaryKey" in annotations:
            primary_key.append(column)
            arguments = annotations["PrimaryKey"] or ""
            if "isSequenceUsedForSorting" in arguments:
                field["sequence"] = True
            translation_types.append(_translation_record_id_type(arguments))
        fields.append(field)

    table_record: dict = {
        "presence": presence,
        "primary_key": primary_key,
        # Parallel to primary_key: which translations.txt id each key column matches against.
        # byTranslationKey is generated from these, and it is not a string comparison against
        # the primary key: see rules/_shared/translations.py.
        "primary_key_translation_types": translation_types,
        "fields": fields,
    }
    # singleRow drives more_than_one_entity. It is an argument to @GtfsTable, so
    # it is generated rather than hand-listed: at v8.0.1 only feed_info.txt sets
    # it, but a hand-written list would silently miss the second one.
    if re.search(r"singleRow\s*=\s*true", annotation):
        table_record["single_row"] = True
    # maxCharsPerColumn overrides univocity's 4,096-character column cap. -1 means unlimited.
    # At v8.0.1 only areas.txt sets it, and a hand-written list would miss the second one.
    cap = re.search(r"maxCharsPerColumn\s*=\s*(-?\d+)", annotation)
    if cap is not None:
        table_record["max_chars_per_column"] = int(cap.group(1))
    return filename, table_record


def _translation_record_id_type(arguments: str) -> str:
    """`@PrimaryKey(translationRecordIdType = ...)`, which defaults to RECORD_ID.

    The default matters: most key columns carry no argument at all and still match
    `record_id`, so an absent annotation is RECORD_ID rather than UNSUPPORTED.
    """
    for name in ("RECORD_SUB_ID", "UNSUPPORTED", "RECORD_ID"):
        if name in arguments:
            return name
    return "RECORD_ID"


def head_commit(checkout: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--tag", default="v8.0.1")
    args = parser.parse_args()

    root = Path(args.checkout)
    cache: dict = {}
    tables = {}
    for path in sorted(root.rglob("Gtfs*Schema.java")):
        if "/test/" in str(path):
            continue
        parsed = parse_schema(path, root, cache)
        if parsed:
            tables[parsed[0]] = parsed[1]

    payload = {
        "_meta": {
            "upstream": "https://github.com/MobilityData/gtfs-validator.git",
            "tag": args.tag,
            "commit": head_commit(root),
        },
        "tables": dict(sorted(tables.items())),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    total = sum(len(t["fields"]) for t in tables.values())
    print(f"wrote {OUT} with {len(tables)} tables and {total} fields")


if __name__ == "__main__":
    main()
