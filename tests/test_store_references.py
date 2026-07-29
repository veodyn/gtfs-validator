"""The anti-join behind foreign_key_violation, and the NULL trap inside it."""

from __future__ import annotations

from gtfs_validator.schema import Field, FieldType, Presence, TableSchema
from gtfs_validator.store import FeedStore


def _schema(filename, *names):
    return TableSchema(
        filename=filename,
        presence=Presence.OPTIONAL,
        primary_key=(),
        fields=tuple(
            Field(name=name, type=FieldType.ID, presence=Presence.OPTIONAL) for name in names
        ),
    )


def _store(tables):
    store = FeedStore.open()
    for filename, columns, rows in tables:
        schema = _schema(filename, *columns)
        store.create_table(schema)
        store.insert_rows(schema, rows)
    return store


def test_only_the_unmatched_rows_come_back_in_row_order():
    store = _store(
        [
            ("parent.txt", ["key"], [{"_row_number": 2, "key": "A"}]),
            (
                "child.txt",
                ["ref"],
                [
                    {"_row_number": 2, "ref": "A"},
                    {"_row_number": 3, "ref": "GHOST"},
                    {"_row_number": 4, "ref": "OTHER"},
                ],
            ),
        ]
    )
    found = list(store.rows_missing_reference("child.txt", "ref", [("parent.txt", "key", False)]))
    assert [(row["_row_number"], row["value"]) for row in found] == [(3, "GHOST"), (4, "OTHER")]


def test_an_absent_child_value_is_not_a_violation():
    """`!hasX()` continues upstream, measured on `fkv3`."""
    store = _store(
        [
            ("parent.txt", ["key"], [{"_row_number": 2, "key": "A"}]),
            ("child.txt", ["ref"], [{"_row_number": 2, "ref": None}]),
        ]
    )
    assert list(store.rows_missing_reference("child.txt", "ref", [("parent.txt", "key", False)])) == []


def test_a_null_parent_key_does_not_silence_every_notice():
    """`x NOT IN (SELECT k ...)` is NULL, not true, once one k is NULL.

    Without the subquery's own NULL filter this returns nothing at all, so one parent row with an
    empty key would suppress the whole reference. The failure mode is silence, which is why it gets
    a test of its own rather than being left to a probe.
    """
    store = _store(
        [
            (
                "parent.txt",
                ["key"],
                [{"_row_number": 2, "key": "A"}, {"_row_number": 3, "key": None}],
            ),
            ("child.txt", ["ref"], [{"_row_number": 2, "ref": "GHOST"}]),
        ]
    )
    found = list(store.rows_missing_reference("child.txt", "ref", [("parent.txt", "key", False)]))
    assert [row["value"] for row in found] == ["GHOST"]


def test_a_key_in_either_parent_resolves():
    """The multi-parent case: calendar.txt or calendar_dates.txt, measured on `fkv6`."""
    store = _store(
        [
            ("one.txt", ["key"], [{"_row_number": 2, "key": "A"}]),
            ("two.txt", ["key"], [{"_row_number": 2, "key": "B"}]),
            (
                "child.txt",
                ["ref"],
                [
                    {"_row_number": 2, "ref": "A"},
                    {"_row_number": 3, "ref": "B"},
                    {"_row_number": 4, "ref": "C"},
                ],
            ),
        ]
    )
    parents = [("one.txt", "key", False), ("two.txt", "key", False)]
    found = list(store.rows_missing_reference("child.txt", "ref", parents))
    assert [row["value"] for row in found] == ["C"]


def test_a_parent_table_that_does_not_exist_leaves_every_row_unmatched():
    """An absent optional parent file reports, measured on `fkv4`: no shapes.txt, still reported."""
    store = _store([("child.txt", ["ref"], [{"_row_number": 2, "ref": "SH1"}])])
    found = list(store.rows_missing_reference("child.txt", "ref", [("shapes.txt", "shape_id", False)]))
    assert [row["value"] for row in found] == ["SH1"]


def test_an_index_parent_reads_an_absent_key_as_the_empty_string():
    """Measured on `fkv31`: fare_rules.origin_id is "" and no stop declares a zone_id, jar silent.

    Upstream builds an @Index from the getter with no presence guard, so a parent row whose key is
    absent is indexed under "" and an empty child key resolves against it.
    """
    store = _store(
        [
            ("parent.txt", ["key"], [{"_row_number": 2, "key": None}]),
            ("child.txt", ["ref"], [{"_row_number": 2, "ref": ""}]),
        ]
    )
    found = list(store.rows_missing_reference("child.txt", "ref", [("parent.txt", "key", True)]))
    assert [row["value"] for row in found] == []


def test_a_primary_key_parent_does_not_read_an_absent_key_as_the_empty_string():
    """Measured on `fkv34`: routes.agency_id is "" and the lone agency omits agency_id, jar reports.

    The pair to the test above, and the reason `defaults_empty` is per parent rather than a constant:
    agency.agency_id is a single-column primary key, stops.zone_id is an @Index, and the jar treats
    the same shape of feed differently for each.
    """
    store = _store(
        [
            ("parent.txt", ["key"], [{"_row_number": 2, "key": None}]),
            ("child.txt", ["ref"], [{"_row_number": 2, "ref": ""}]),
        ]
    )
    found = list(store.rows_missing_reference("child.txt", "ref", [("parent.txt", "key", False)]))
    assert [row["value"] for row in found] == [""]


def test_skip_empty_passes_over_an_empty_child_key():
    """The `isEmpty()` guard two hand-written validators use, measured on `fkv32` and `fkv33`."""
    store = _store(
        [
            ("parent.txt", ["key"], [{"_row_number": 2, "key": "A"}]),
            ("child.txt", ["ref"], [{"_row_number": 2, "ref": ""}, {"_row_number": 3, "ref": "G"}]),
        ]
    )
    parents = [("parent.txt", "key", False)]
    guarded = store.rows_missing_reference("child.txt", "ref", parents, skip_empty=True)
    assert [row["value"] for row in guarded] == ["G"]
    # Without the guard the empty key is reported, which is what `fkv30` shows for a generated
    # reference: an empty route_id draws a notice whose fieldValue is "".
    plain = store.rows_missing_reference("child.txt", "ref", parents)
    assert [row["value"] for row in plain] == ["", "G"]
