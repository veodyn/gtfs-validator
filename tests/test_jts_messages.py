"""The generated JTS message table invalid_geometry will report.

A drift test, not a behaviour test: it pins what the pinned jar's JTS says, so a
regenerated file that changes a message shows up here rather than inside a notice.
"""

from __future__ import annotations

import json
from importlib.resources import files

import pytest

TABLE = json.loads(files("gtfs_validator.data").joinpath("jts_messages.json").read_text())


def test_every_topology_error_has_a_message():
    errors = TABLE["topology_errors"]
    assert len(errors) == 12
    assert all(message and message != "UNAVAILABLE" for message in errors.values())


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("HOLE_OUTSIDE_SHELL", "Hole lies outside shell"),
        ("NESTED_HOLES", "Holes are nested"),
        ("DISCONNECTED_INTERIOR", "Interior is disconnected"),
        ("SELF_INTERSECTION", "Self-intersection"),
        ("RING_SELF_INTERSECTION", "Ring Self-intersection"),
        ("TOO_FEW_POINTS", "Too few distinct points in geometry component"),
        ("INVALID_COORDINATE", "Invalid Coordinate"),
        ("RING_NOT_CLOSED", "Ring is not closed"),
    ],
)
def test_the_wording_is_what_the_jar_reports(name, message):
    assert TABLE["topology_errors"][name] == message


def test_a_three_point_ring_is_accepted_by_the_pinned_jts():
    """The bound is three points, not four.

    A plain reading of JTS says a LinearRing needs four points, and that reading is what a
    transcription would have encoded. The pinned jar accepts a three-point ring and words
    the two-point refusal as "must be 0 or >= 3", which is why this table is generated
    rather than written out.
    """
    construction = TABLE["construction_errors"]
    assert construction["three_points"] == "ACCEPTED"
    assert construction["empty"] == "ACCEPTED"
    assert construction["two_points"] == (
        "Invalid number of points in LinearRing (found 2 - must be 0 or >= 3)"
    )
    # One point never reaches the LinearRing check: LineString's runs first.
    assert construction["one_point"] == (
        "Invalid number of points in LineString (found 1 - must be 0 or >= 2)"
    )


def test_an_unclosed_ring_is_refused_at_construction():
    """So the notice carries the exception's wording, not "Ring is not closed"."""
    assert TABLE["construction_errors"]["unclosed_ring"] == (
        "Points of LinearRing do not form a closed linestring"
    )
    assert TABLE["topology_errors"]["RING_NOT_CLOSED"] == "Ring is not closed"


def test_the_measured_cases_record_which_error_wins():
    """A bowtie ring reports Self-intersection, not Ring Self-intersection, and a NaN
    coordinate is refused for not closing the ring rather than for being invalid. Both
    contradict the obvious guess, so the shapes stay recorded: if a regenerated table
    changes which error a known shape produces, that belongs in review.
    """
    cases = TABLE["measured_cases"]
    assert cases["ring_self_intersection"] == "5\tSelf-intersection"
    assert cases["invalid_coordinate"].startswith("THROWS\t")
    assert cases["too_few_distinct_points"] == "9\tToo few distinct points in geometry component"
