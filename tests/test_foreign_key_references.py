"""The generated reference list: what upstream checks, and in what order.

The count and the exclusion are both measured. `fkv10` proves upstream ignores
location_group_stops' two references, whose annotations are commented out in the Java; a generator
that reads a commented annotation as live would have us reporting on a feed the jar passes.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src/gtfs_validator/data/table_schemas.json"


def references():
    tables = json.loads(DATA.read_text())["tables"]
    return [
        (name, field["name"], field["references"])
        for name, table in tables.items()
        for field in table["fields"]
        if field.get("references")
    ]


def test_upstream_checks_forty_four_generated_references():
    """46 @ForeignKey lines in the pinned schemas, two of them commented out."""
    assert len(references()) == 44


def test_location_group_stops_references_are_not_read_from_comments():
    """Measured on `fkv10`: every reference there broken, and the jar reports nothing."""
    assert [name for name, _, _ in references() if name == "location_group_stops.txt"] == []


def test_a_reference_records_the_upstream_validator_name():
    """The sample order is ascending class name, so the name is data the rule sorts on."""
    found = [
        reference
        for name, field, reference in references()
        if name == "trips.txt" and field == "route_id"
    ]
    assert found == [
        {
            "table": "routes.txt",
            "field": "route_id",
            "validator": "GtfsTripRouteIdForeignKeyValidator",
        }
    ]


def test_the_rule_covers_fifty_checks():
    """44 generated plus 6 hand-written field checks from 5 upstream classes."""
    from gtfs_validator.rules._shared.foreign_keys import references

    assert len(references()) == 50
