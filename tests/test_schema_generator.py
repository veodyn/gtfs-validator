"""The schema generator's field parsing, which nothing exercised before.

The generated JSON is committed, so a generator defect shows up only at the next pin refresh, when
the drift it introduces looks like an upstream change. These tests run the parsing directly on
hand-written Java so that the defect fails here instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from _schema_fields import build_field, parse_annotations, strip_line_comments, validator_name


def test_a_commented_out_annotation_is_removed():
    """Probe `fkv10`: upstream comments out both of location_group_stops' @ForeignKey lines."""
    java = '  //  @ForeignKey(table = "stops.txt", field = "stop_id")\n  @Required\n'
    assert "@ForeignKey" not in strip_line_comments(java)
    assert "@Required" in strip_line_comments(java)


def test_a_double_slash_inside_a_string_literal_survives():
    """A URL in an annotation argument is not a comment.

    Deleting every `//...` truncates this to `@DefaultValue("https:`, and MEMBER_RE still matches the
    accessor below it, so the field would arrive with its default silently dropped. No schema at the
    current pin has one, which is what makes it a pin-refresh hazard worth a test rather than a
    comment.
    """
    java = '  @DefaultValue("https://example.test")  // a trailing comment\n'
    stripped = strip_line_comments(java)
    assert '"https://example.test"' in stripped
    assert "a trailing comment" not in stripped


def test_a_foreign_key_records_its_target_and_validator_name():
    annotations = parse_annotations('@ForeignKey(table = "trips.txt", field = "trip_id")')
    field = build_field("trip_id", "String", annotations, Path(), {}, "GtfsStopTime", "tripId")
    assert field["references"] == {
        "table": "trips.txt",
        "field": "trip_id",
        "validator": "GtfsStopTimeTripIdForeignKeyValidator",
    }


def test_the_validator_name_capitalises_the_accessor_without_touching_the_rest():
    """`childFile.className() + capitalize(childField.name()) + "ForeignKeyValidator"` upstream.

    `capitalize` is not `title`: `fromStopId` becomes `FromStopId`, not `Fromstopid`.
    """
    assert validator_name("GtfsTransfer", "fromStopId") == (
        "GtfsTransferFromStopIdForeignKeyValidator"
    )
