"""The four stop-to-shape codes' context keys: their order, and the Python type of each value.

Neither is visible to anything else in the project. `tools/diff_against_upstream.sh` serialises
every sample with `sort_keys=True` before diffing, so a rule emitting Gson's fields in the wrong
order matches the jar on every probe feed, and dict equality in the other test modules cannot see
order either. Python's `1 == 1.0 == True` hides the types the same way.

Pinned against `canonical_notices.json`, which is generated from upstream at the pin, rather than
against a list retyped from the Java: a field reordered upstream then fails this test instead of
silently agreeing with a stale copy.
"""

from __future__ import annotations

import pytest

from gtfs_validator.manifest import load_manifest
from shapematchfeed import (
    FAR_SHAPE,
    OUT_OF_ORDER,
    TOO_FAR,
    TOO_FAR_USER_DISTANCE,
    TOO_MANY_MATCHES,
    far_feed,
    feed,
    fire,
    shape,
    stop_times,
    stops,
    trip,
)


def _too_far():
    return fire(TOO_FAR, far_feed())[0]


def _too_far_user_distance():
    view = feed(
        stops_rows=stops(
            ("S1", "First", 40.0, -74.0),
            ("S2", "Middle", 40.0, -73.95),
            ("S3", "Last", 40.0, -73.9),
        ),
        trips_rows=[trip()],
        times_rows=stop_times("T1", ("S1", 0), ("S2", 8000), ("S3", 8530)),
        shape_rows=shape((40.0, -74.0, 0), (40.0, -73.95, 4265), (40.0, -73.9, 8530)),
    )
    return fire(TOO_FAR_USER_DISTANCE, view)[0]


def _too_many_matches():
    points = []
    for visit in range(25):
        points.append((40.0, round(-74.0 + visit * 0.000001, 6)))
        points.append((40.01, round(-74.0 + visit * 0.001, 6)))
        points.append((40.01, round(-74.0 + visit * 0.001 + 0.0005, 6)))
    view = feed(
        stops_rows=stops(("S1", "Visited", 40.0, -74.0), ("S2", "Last", 40.01, -73.9755)),
        trips_rows=[trip()],
        times_rows=stop_times("T1", "S1", "S2"),
        shape_rows=shape(*points),
    )
    return fire(TOO_MANY_MATCHES, view)[0]


def _out_of_order():
    view = feed(
        stops_rows=stops(("S1", "East", 40.0, -73.99), ("S2", "West", 40.0, -74.0)),
        trips_rows=[trip()],
        times_rows=stop_times("T1", "S1", "S2"),
        shape_rows=shape(*FAR_SHAPE),
    )
    return fire(OUT_OF_ORDER, view)[0]


CASES = [
    (TOO_FAR, _too_far),
    (TOO_FAR_USER_DISTANCE, _too_far_user_distance),
    (TOO_MANY_MATCHES, _too_many_matches),
    (OUT_OF_ORDER, _out_of_order),
]


@pytest.mark.parametrize(("code", "build"), CASES, ids=[code for code, _ in CASES])
def test_the_context_keys_are_in_the_order_upstream_declares_them(code, build):
    assert list(build()) == list(load_manifest().context_fields_of(code))


@pytest.mark.parametrize(("code", "build"), CASES, ids=[code for code, _ in CASES])
def test_each_context_value_has_the_type_the_manifest_declares(code, build):
    """`type(...) is int` rather than `isinstance`, because `bool` is a subclass of `int`.

    A `True` here would serialise as `true` where the jar writes `1`, and a float row number as
    `2.0` where it writes `2`. The report writer passes the context through untouched, so this is
    the only place either is caught.
    """
    context = build()
    for field, kind in load_manifest().context_fields_of(code).items():
        value = context[field]
        if kind == "integer":
            assert type(value) is int, f"{field} is {type(value).__name__}"
        elif kind == "string":
            assert type(value) is str, f"{field} is {type(value).__name__}"
        elif kind == "number":
            assert type(value) is float, f"{field} is {type(value).__name__}"
        else:
            # `match` is an S2LatLng, which Gson writes as a two-element array of degrees rather
            # than as an object with named fields. Measured on the probe feeds.
            assert kind == "object", f"{field} declares an unhandled kind {kind}"
            assert type(value) is list and len(value) == 2, f"{field} is {value!r}"
            assert all(type(part) is float for part in value), f"{field} is {value!r}"
