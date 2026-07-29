"""`gtfs_validator.s2point` against values dumped from the S2 classes in the pinned jar.

Every number here was produced by `tools/_oracle/DumpEdgeGeometry.java`, never by hand and never
by reasoning about spherical geometry. The four stop-to-shape notice codes report a matched
lat/lng and a distance in metres as context, so parity level C puts the last digit of these
operations in the contract, and the last digit of an atan2 is not something to deduce.

`tools/diff_edge_geometry_against_s2.py` runs the same comparison over a generated corpus. These
tests are the subset a failing build should name, chosen for the shapes the matcher actually hits:
a stop beside a segment, a stop past the end of one, a degenerate segment whose endpoints
coincide, and the poles.
"""

from __future__ import annotations

import math

import pytest

from gtfs_validator.s2earth import vector_distance_meters
from gtfs_validator.s2point import (
    approx_equals,
    closest_point,
    interpolate,
    to_lat_lng_degrees,
    to_point,
)


def _closest_degrees(
    stop: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> tuple[float, float, float]:
    """The matched lat, lng and distance in metres, which is what a notice carries."""
    x = to_point(*stop)
    match = closest_point(x, to_point(*start), to_point(*end))
    latitude, longitude = to_lat_lng_degrees(match)
    return latitude, longitude, vector_distance_meters(x, match)


def test_closest_point_beside_a_segment_matches_the_jar():
    """The sm1 probe's geometry: a stop 300 m north of an east-west segment.

    The jar puts these values in `stop_too_far_from_shape`, so this pins the notice's context and
    not just the geometry. The location agrees to the last digit. The distance does not, and the
    difference is divergence 12: the jar reports 333.58530340111884, 8e-10 m away, because one ulp
    of `sin` inside `toPoint` is amplified by the cancellation in a cross product of two nearly
    parallel unit vectors. Both values are pinned rather than compared with a tolerance, so that a
    change in the arithmetic shows up as a failure naming the digit that moved.
    """
    assert _closest_degrees((40.003, -73.995), (40.0, -74.0), (40.0, -73.995)) == (
        40.00000000000236,
        -73.99500010983789,
        333.5853034003414,
    )


def test_the_neighbouring_segment_is_a_worse_match_by_half_a_nanometre():
    """Why the notice names the first segment: it wins, and only just.

    The same stop sits at the shared vertex of two segments, and the two distances differ in the
    tenth digit. `keepBestMatch` compares with a strict `<`, so the earlier segment keeps the
    match. A port that used `<=` would report the same distance against a different shape index,
    and nothing in the reported numbers would show it.

    The ordering is what matters here and the ordering is what the jar agrees on: it computes
    333.58530340111884 and 333.5853034016623, the same way round, 5e-10 m apart.
    """
    _, _, first = _closest_degrees((40.003, -73.995), (40.0, -74.0), (40.0, -73.995))
    _, _, second = _closest_degrees((40.003, -73.995), (40.0, -73.995), (40.0, -73.99))
    assert first == 333.5853034003414
    assert second == 333.5853034009824
    assert first < second


def test_a_stop_on_a_degenerate_segment_matches_at_zero():
    """A shape row repeated verbatim, which sends `robustCrossProd` down its ortho fallback.

    Exact on both sides, and it has to be: the fallback is the only reason the division by the
    cross product's squared norm does not divide by zero.
    """
    assert _closest_degrees((40.0, -74.0), (40.0, -74.0), (40.0, -74.0)) == (40.0, -74.0, 0.0)


def test_a_stop_beside_a_segment_midpoint_matches_the_jar():
    """The jar reports 40.000000026856455 and 111.19211486986427 for this one.

    Both differ from ours in their last two digits, for the reason
    `test_closest_point_beside_a_segment_matches_the_jar` records. 4e-10 m of latitude and
    4e-10 m of distance.
    """
    assert _closest_degrees((40.001, -73.9975), (40.0, -74.0), (40.0, -73.995)) == (
        40.00000002685646,
        -73.9975,
        111.19211487030178,
    )


def test_near_the_pole_the_match_is_not_on_the_parallel():
    """A segment between two points at 89 degrees north bulges polewards, and atan2 says so.

    A shape crossing the arctic is legal, and the great circle between two points on a parallel
    is not the parallel. The matched latitude here is 89.29, well north of both endpoints.
    """
    assert _closest_degrees((89.9, 10.0), (89.0, 0.0), (89.0, 90.0)) == (
        89.29053478297634,
        40.36239367022471,
        69522.19472347909,
    )


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [
        (0.5, (40.00001074258783, -73.95)),
        (0.0, (40.0, -74.0)),
        (1.0, (40.0, -73.9)),
        (0.3333333333333333, (40.33428752836281, -73.66996901163982)),
    ],
)
def test_interpolate_matches_the_jar(fraction, expected):
    """`interpolate` short-circuits at 0 and 1, returning the endpoint untouched.

    The 0.5 case is the one that shows the interpolation is spherical rather than linear: the
    midpoint of two points on the same parallel sits a hundred nanodegrees north of it. The jar
    puts that midpoint at 40.000010742587826, one digit from ours; the other three agree exactly,
    because two of them are returned unrounded by the short circuit.
    """
    start = to_point(40.0, -74.0)
    end = to_point(40.0, -73.9) if fraction != 0.3333333333333333 else to_point(41.0, -73.0)
    assert to_lat_lng_degrees(interpolate(fraction, start, end)) == expected


def test_interpolating_a_degenerate_edge_yields_nan_rather_than_raising():
    """A shape with two identical rows, which upstream divides by zero over.

    Measured: the jar prints `NaN NaN` for the midpoint of an edge whose endpoints coincide,
    because Java's `0.0 / 0.0` is NaN. Python's `/` raises `ZeroDivisionError` instead, so a
    literal transcription turns a legal if silly feed into a crash. Notices are data, not
    exceptions, and that applies to the geometry underneath them.

    The zero fraction still short-circuits to the endpoint, so the NaN needs a fraction the short
    circuit does not catch.
    """
    point = to_point(40.0, -74.0)
    latitude, longitude = to_lat_lng_degrees(interpolate(0.5, point, point))
    assert math.isnan(latitude)
    assert math.isnan(longitude)
    assert to_lat_lng_degrees(interpolate(0.0, point, point)) == (40.0, -74.0)


def test_approx_equals_uses_the_default_epsilon():
    """1e-15 radians is about 6 nanometres on the ground, so a tenth of a microdegree is not equal."""
    assert approx_equals(to_point(40.0, -74.0), to_point(40.0, -74.0))
    assert not approx_equals(to_point(40.0, -74.0), to_point(40.0000000001, -74.0))


def test_to_lat_lng_degrees_round_trips_a_coordinate():
    """Not exactly, and the difference is the point.

    `to_point` and back is two trigonometric conversions, so a coordinate does not survive
    unchanged. Rules that report a matched location report what came back, not what went in.
    """
    latitude, longitude = to_lat_lng_degrees(to_point(40.7128, -74.006))
    assert latitude == pytest.approx(40.7128, abs=1e-12)
    assert longitude == pytest.approx(-74.006, abs=1e-12)


def test_to_point_is_a_unit_vector():
    x, y, z = to_point(40.0, -74.0)
    assert math.isclose(x * x + y * y + z * z, 1.0, rel_tol=0, abs_tol=1e-15)
