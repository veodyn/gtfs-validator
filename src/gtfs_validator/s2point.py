"""The S2 vector operations `ShapeToStopMatchingValidator` matches stops to shapes with.

Transcribed from `com.google.geometry:s2-geometry` at 2.0.0, the version the pinned jar bundles,
read from that release's sources jar rather than from the current library: the two differ, and the
jar is the oracle. `tools/diff_edge_geometry_against_s2.py` compares this port against the classes
in the jar over a generated corpus, and `tests/test_s2point.py` pins the cases the matcher hits.

A point here is a plain three-tuple of doubles rather than a class. The matcher builds one per
shape point and one per stop and then compares thousands of pairs, and a tuple costs no attribute
lookups; nothing in the port mutates a point.

Two details carry real weight, both of them about arithmetic order rather than about geometry:

* Every operation keeps upstream's exact sequence of multiplications and additions. The four
  stop-to-shape codes report a matched latitude and longitude as notice context, so parity level C
  makes the last bit of an atan2 part of the contract, and floating-point addition does not
  associate. `crossProdNorm` is spelled out inline for that reason, exactly as S2Point does.
* `robustCrossProd` takes the cross product of `(b + a)` and `(b - a)` rather than of `a` and `b`.
  Mathematically that is twice the same vector; numerically it is the reason the library gives a
  stable answer for two points that differ in one low bit, which is what a shape with a repeated
  coordinate hands it.
"""

from __future__ import annotations

import math

# `S1Angle.degrees` multiplies by this, and `latDegrees` divides by it, both as one operation
# against a compile-time constant. Spelled out rather than calling math.radians so the rounding is
# checkable against the Java.
_DEGREES_TO_RADIANS = math.pi / 180.0
_RADIANS_TO_DEGREES = 180.0 / math.pi

Point = tuple[float, float, float]

# `S2.ORTHO_BASES`, the arbitrary bases `ortho` falls back on. The components are deliberately
# not axis-aligned so that the cross product with any input is non-degenerate.
_ORTHO_BASES: tuple[Point, Point, Point] = (
    (1.0, 0.0053, 0.00457),
    (0.012, 1.0, 0.00457),
    (0.012, 0.0053, 1.0),
)


def to_point(latitude: float, longitude: float) -> Point:
    """`S2LatLng.fromDegrees(...).toPoint()`, in its own operation order so the rounding matches."""
    phi = latitude * _DEGREES_TO_RADIANS
    theta = longitude * _DEGREES_TO_RADIANS
    cos_phi = math.cos(phi)
    return (math.cos(theta) * cos_phi, math.sin(theta) * cos_phi, math.sin(phi))


def to_lat_lng_degrees(point: Point) -> tuple[float, float]:
    """`new S2LatLng(point)` read back in degrees, which is what a notice's `match` carries.

    atan2 rather than asin, as the library notes, because the vector is not necessarily unit
    length after a normalize and atan2 stays accurate near the poles. The `+ 0.0` upstream adds to
    each component exists to fold -0.0 onto +0.0 so that two equal points format alike; Python's
    atan2 has the same signed-zero behaviour, so the additions are kept for the same reason.
    """
    x, y, z = point
    latitude = math.atan2(z + 0.0, math.sqrt(x * x + y * y))
    longitude = math.atan2(y + 0.0, x + 0.0)
    return (_RADIANS_TO_DEGREES * latitude, _RADIANS_TO_DEGREES * longitude)


def angle(first: Point, second: Point) -> float:
    """`S2Point.angle`: the angle between two vectors, in radians.

    `atan2(|a x b|, a . b)` rather than `acos(a . b)`, which loses precision for the small angles
    a transit feed is made of.
    """
    return math.atan2(_cross_norm(first, second), _dot(first, second))


def closest_point(location: Point, start: Point, end: Point) -> Point:
    """`S2EdgeUtil.getClosestPoint`: the point on the great-circle edge nearest `location`.

    The perpendicular foot on the great circle through the edge, when that foot lies between the
    endpoints, and otherwise whichever endpoint is nearer in 3D. The containment test is two
    signed volumes rather than a comparison of angles, which is what keeps it exact for an edge
    whose endpoints nearly coincide.
    """
    a_cross_b = robust_cross_prod(start, end)
    foot = _sub(location, _mul(a_cross_b, _dot(location, a_cross_b) / _norm2(a_cross_b)))
    if _ccw(a_cross_b, start, foot) and _ccw(foot, end, a_cross_b):
        return _normalize(foot)
    # Compared as squared chord lengths, not as angles: monotonic in the angle and cheaper.
    return start if _distance2(location, start) <= _distance2(location, end) else end


def interpolate(fraction: float, start: Point, end: Point) -> Point:
    """`S2EdgeUtil.interpolate`: the point `fraction` of the way along the edge, on the sphere.

    Not `(1 - t) * a + t * b` normalized, which would bunch points towards the middle of a long
    edge. The endpoints are returned untouched at 0 and 1, which matters for a stop whose
    `shape_dist_traveled` lands exactly on a shape vertex: it gets that vertex, not a re-derived
    approximation of it.
    """
    if fraction == 0:
        return start
    if fraction == 1:
        return end
    edge_radians = angle(start, end)
    return _interpolate_at_distance(fraction * edge_radians, start, end, edge_radians)


def approx_equals(first: Point, second: Point, max_error: float = 1e-15) -> bool:
    """`S2.approxEquals` at its default epsilon, which is about 6 nm on the Earth's surface.

    The matcher asks this before interpolating, because the interpolation is undefined for an edge
    whose endpoints are the same point, and a shape with a duplicated row is common.
    """
    return angle(first, second) <= max_error


def robust_cross_prod(first: Point, second: Point) -> Point:
    """`S2.robustCrossProd`: a vector orthogonal to both, stable when they nearly coincide."""
    result = _cross(_add(second, first), _sub(second, first))
    if result != (0.0, 0.0, 0.0):
        return result
    # Mathematically the answer is zero, and the library returns an arbitrary orthogonal vector
    # instead so that callers dividing by its norm do not divide by zero.
    return _ortho(first)


def _interpolate_at_distance(
    along_radians: float, start: Point, end: Point, edge_radians: float
) -> Point:
    """`S2EdgeUtil.interpolateAtDistance`, the two-coefficient form.

    The result is a linear combination `e * start + f * end` whose coefficients come from the
    parallel and perpendicular components of the parallelogram the two vectors span. Normalized at
    the end even though it is unit length in exact arithmetic, because the matcher feeds
    interpolated points back into further distance calls.

    The division is Java's, not Python's. For an edge whose endpoints coincide both sines are zero,
    and Java's `0.0 / 0.0` is NaN where Python's raises `ZeroDivisionError`: a raise here would
    turn a shape with a duplicated row into a crash instead of into upstream's NaN coordinates.
    The matcher guards this case with `approx_equals` before it ever calls in, so the guard is what
    a real feed meets; this keeps the unguarded path faithful rather than fatal.
    """
    f = _java_divide(math.sin(along_radians), math.sin(edge_radians))
    e = math.cos(along_radians) - f * math.cos(edge_radians)
    return _normalize(_add(_mul(start, e), _mul(end, f)))


def _java_divide(numerator: float, denominator: float) -> float:
    """`numerator / denominator` under IEEE 754, which is what a Java double division does."""
    if denominator != 0.0:
        return numerator / denominator
    if numerator == 0.0 or numerator != numerator:
        return math.nan
    return math.inf if (numerator > 0.0) == (not _is_negative_zero(denominator)) else -math.inf


def _is_negative_zero(value: float) -> bool:
    """Whether `value` is -0.0, which divides to the opposite infinity from +0.0."""
    return math.copysign(1.0, value) < 0.0


def _ccw(first: Point, second: Point, third: Point) -> bool:
    """`S2EdgeUtil.ccw`: whether the three vectors form a positively oriented triple."""
    return _scalar_triple_product(second, third, first) > 0


def _scalar_triple_product(first: Point, second: Point, third: Point) -> float:
    """`first . (second x third)`, spelled out in S2Point's own order."""
    x = second[1] * third[2] - second[2] * third[1]
    y = second[2] * third[0] - second[0] * third[2]
    z = second[0] * third[1] - second[1] * third[0]
    return first[0] * x + first[1] * y + first[2] * z


def _cross(first: Point, second: Point) -> Point:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _cross_norm(first: Point, second: Point) -> float:
    """`S2Point.crossProdNorm`, which forms the components inline rather than building a vector."""
    x = first[1] * second[2] - first[2] * second[1]
    y = first[2] * second[0] - first[0] * second[2]
    z = first[0] * second[1] - first[1] * second[0]
    return math.sqrt(x * x + y * y + z * z)


def _dot(first: Point, second: Point) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def _add(first: Point, second: Point) -> Point:
    return (first[0] + second[0], first[1] + second[1], first[2] + second[2])


def _sub(first: Point, second: Point) -> Point:
    return (first[0] - second[0], first[1] - second[1], first[2] - second[2])


def _mul(point: Point, scale: float) -> Point:
    return (point[0] * scale, point[1] * scale, point[2] * scale)


def _norm2(point: Point) -> float:
    return point[0] * point[0] + point[1] * point[1] + point[2] * point[2]


def _distance2(first: Point, second: Point) -> float:
    """`S2Point.getDistance2`: the squared 3D chord length."""
    dx = first[0] - second[0]
    dy = first[1] - second[1]
    dz = first[2] - second[2]
    return dx * dx + dy * dy + dz * dz


def _normalize(point: Point) -> Point:
    """`S2Point.normalize`, which leaves a zero vector alone rather than dividing by zero."""
    norm = math.sqrt(_norm2(point))
    if norm != 0:
        norm = 1.0 / norm
    return _mul(point, norm)


def _ortho(point: Point) -> Point:
    """`S2.ortho`: a unit vector orthogonal to `point`, chosen so that `ortho(-a) == -ortho(a)`."""
    index = _largest_abs_component(point) - 1
    if index < 0:
        index = 2
    return _normalize(_cross(point, _ORTHO_BASES[index]))


def _largest_abs_component(point: Point) -> int:
    """`S2Point.largestAbsComponent`, ties broken exactly as the Java's nested comparisons do."""
    abs_x = abs(point[0])
    abs_y = abs(point[1])
    abs_z = abs(point[2])
    if abs_x > abs_y:
        return 0 if abs_x > abs_z else 2
    return 1 if abs_y > abs_z else 2
