"""`S2Earth.getDistanceMeters`, in both of the overloads upstream measures with.

`S2Earth.getDistanceMeters` is **overloaded**, and the two overloads are different formulas rather
than one wrapping the other. Each multiplies an angle by a fixed mean radius of 6,371,010 m, and
they disagree about the angle:

| Overload | Formula | Called by |
|---|---|---|
| `S2LatLng` | `S2LatLng.getDistance`, the haversine | shape distances, trip-versus-shape distances |
| `S2Point` | `atan2(|a x b|, a . b)` over unit vectors | transfer distances, via `.toPoint()` |

A rule has to use the one its own validator called. This docstring first said upstream "calls one
function for every distance it reports", which was written before anyone had read
`TransferDistanceValidator`, and porting on that basis would have put a wrong number in every
transfer-distance notice. Which overload a validator reaches is a question to answer by reading its
Java, not by reading this file.

Notice codes carry these values as context, so parity level C makes the *last digit* part of the
contract, not just the comparison against a threshold.

That last digit is a measurement, not a deduction. The haversine is a few libm calls, and Java's
`Math.sin` is specified only to within 1 ulp of the true result, so nothing guarantees CPython's
libm agrees. A 1-ulp difference changes the shortest round-tripping decimal, which is exactly what
Gson writes into the report. `tools/diff_distances_against_s2.py` compares this port against the
S2 classes bundled in the pinned jar over a generated corpus, and records what it found.

The thresholds these distances are compared against are small enough to sit inside that
uncertainty: `ShapeIncreasingDistanceValidator` splits on 1.11 m, and 0.00001 degrees of latitude
is 1.1119510126348764 m. So a fixture near a boundary has to be measured, never reasoned about.
"""

from __future__ import annotations

import math

from gtfs_validator.s2point import Point, angle, to_point

# S2Earth.getRadiusMeters(): the sphere with the Earth's surface area, quoted from NASA.
RADIUS_METERS = 6371010.0
# S1Angle.degrees multiplies by this, so the port does too rather than calling math.radians:
# both are one multiplication by the same double, and being explicit makes that checkable.
_DEGREES_TO_RADIANS = math.pi / 180.0


def distance_meters(
    first_lat: float, first_lon: float, second_lat: float, second_lon: float
) -> float:
    """The distance in metres between two points given in degrees.

    Transcribed from `S2LatLng.getDistance`: the haversine, which the library chose because it
    stays stable for the short distances a transit feed contains, at the cost of precision near
    antipodal points. An earlier version of this docstring added "that no rule here reaches",
    which a review disproved with a feed drawing `equal_shape_distance_diff_coordinates` at
    20015118.21194711 m. Two antipodal shape points are a legal, if absurd, feed.

    Faithful for finite coordinates, which is all a loaded row can hold: a latitude that parses
    to NaN or an infinity fails its range check and takes the row out before any rule sees it.
    For non-finite input the two sides part company, and the clamp below is the only place this
    port bothers to match: Python's `math.sin(inf)` raises where Java's returns NaN.
    """
    first_lat_radians = first_lat * _DEGREES_TO_RADIANS
    second_lat_radians = second_lat * _DEGREES_TO_RADIANS
    latitude_term = math.sin(0.5 * (second_lat_radians - first_lat_radians))
    longitude_term = math.sin(
        0.5 * (second_lon * _DEGREES_TO_RADIANS - first_lon * _DEGREES_TO_RADIANS)
    )
    haversine = latitude_term * latitude_term + longitude_term * longitude_term * math.cos(
        first_lat_radians
    ) * math.cos(second_lat_radians)
    # `Math.min(1.0, x)` guards the sqrt against a rounding overshoot past 1. Python's `min` is
    # not the same function: it returns its first argument when a comparison is false, so
    # `min(1.0, nan)` is 1.0 where Java's is NaN. That turned a NaN distance into 20015118 m,
    # half the Earth's circumference, which is a number rather than an absence.
    bounded = haversine if math.isnan(haversine) else min(1.0, haversine)
    return 2 * math.asin(math.sqrt(bounded)) * RADIUS_METERS


def point_distance_meters(
    first_lat: float, first_lon: float, second_lat: float, second_lon: float
) -> float:
    """`S2Earth.getDistanceMeters(S2Point, S2Point)`, which is *not* the haversine above.

    `S2Earth` is overloaded, and the two overloads are different formulas. The `S2LatLng` one
    takes the haversine; the `S2Point` one converts each coordinate to a unit vector and takes
    `atan2(|a x b|, a . b)`. They agree to about a part in 1e12, which is far more than enough
    to differ in the last digit a notice reports, so a rule has to use the overload its own
    validator called. `TransferDistanceValidator` calls `.toPoint()` first and therefore this one.
    """
    return vector_distance_meters(to_point(first_lat, first_lon), to_point(second_lat, second_lon))


def vector_distance_meters(first: Point, second: Point) -> float:
    """The same overload for callers that already hold unit vectors.

    `ShapeToStopMatchingValidator` is one: it converts each stop and shape point once and then
    measures thousands of pairs, including pairs whose second point is a computed match that has no
    lat/lng of its own until the notice is built.
    """
    return angle(first, second) * RADIUS_METERS
