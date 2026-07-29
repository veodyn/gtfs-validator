#!/usr/bin/env python3
"""Differential harness for `gtfs_validator.s2point` against the S2 classes in the pinned jar.

The four stop-to-shape codes report a matched location and a distance as context, so parity level C
puts the last digits of `S2EdgeUtil.getClosestPoint`, `S2EdgeUtil.interpolate` and the conversion
back to degrees in the contract.

This harness measures rather than asserts. Divergence 12 established that the last digit of any
`S2Earth` distance is a libm difference that no amount of careful transcription closes, and that
the `S2Point` overload amplifies one ulp of `sin` into 7e-13 through the cancellation in a cross
product of nearly parallel vectors. The same cancellation runs twice here, once in
`robustCrossProd` and once in the final angle, so the exit code is not what matters: the reported
distribution is. A regression shows up as a jump in the worst relative difference, not as a
mismatch count going from zero to non-zero.

Usage:
    python3 tools/diff_edge_geometry_against_s2.py [--jar PATH] [--verbose]
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gtfs_validator.s2earth import vector_distance_meters
from gtfs_validator.s2point import (
    approx_equals,
    closest_point,
    interpolate,
    to_lat_lng_degrees,
    to_point,
)

ORACLE = Path(__file__).resolve().parent / "_oracle" / "DumpEdgeGeometry.java"
# `gettempdir()` is the per-user directory on macOS, which is not where the jar is kept.
DEFAULT_JAR = os.environ.get("GTFS_JAR", "/tmp/gtfs-validator.jar")  # noqa: S108


def _closest_cases() -> list[tuple[float, ...]]:
    """Stop-versus-segment triples, in the shapes the matcher meets."""
    cases: list[tuple[float, ...]] = []

    # The probe geometries: a stop beside a segment, at its end, and past both ends.
    cases.extend(
        [
            (40.003, -73.995, 40.0, -74.0, 40.0, -73.995),
            (40.003, -73.995, 40.0, -73.995, 40.0, -73.99),
            (40.001, -73.9975, 40.0, -74.0, 40.0, -73.995),
            (40.0, -74.1, 40.0, -74.0, 40.0, -73.995),
            (40.0, -73.9, 40.0, -74.0, 40.0, -73.995),
        ]
    )

    # A degenerate segment, which a shape with a repeated row produces and which sends
    # robustCrossProd down its ortho fallback.
    cases.append((40.0, -74.0, 40.0, -74.0, 40.0, -74.0))
    cases.append((40.001, -74.0, 40.0, -74.0, 40.0, -74.0))

    # Segments a metre long, which is what a densely sampled shape is made of.
    for step in (1e-6, 1e-5, 1e-4, 1e-3):
        cases.append((40.0 + step, -74.0, 40.0, -74.0, 40.0, -74.0 + step))
        cases.append((40.0 - step, -74.0 + step / 2, 40.0, -74.0, 40.0, -74.0 + step))

    # Latitude bands and the antimeridian, where the longitude term is scaled by cos(lat).
    for latitude in (-89.0, -60.0, 0.0, 23.5, 60.0, 89.0):
        cases.append((latitude + 0.001, 0.0005, latitude, 0.0, latitude, 0.001))
        cases.append((latitude, 179.9995, latitude, 179.999, latitude, -179.999))

    # Seeded, so a failure can be quoted in a commit and reproduced.
    rng = random.Random(20260726)  # noqa: S311 - corpus generation, not cryptography
    for _ in range(300):
        latitude, longitude = rng.uniform(-80.0, 80.0), rng.uniform(-180.0, 180.0)
        cases.append(
            (
                latitude + rng.uniform(-0.005, 0.005),
                longitude + rng.uniform(-0.005, 0.005),
                latitude,
                longitude,
                latitude + rng.uniform(-0.01, 0.01),
                longitude + rng.uniform(-0.01, 0.01),
            )
        )
    for _ in range(200):
        cases.append(
            (
                rng.uniform(-90.0, 90.0),
                rng.uniform(-180.0, 180.0),
                rng.uniform(-90.0, 90.0),
                rng.uniform(-180.0, 180.0),
                rng.uniform(-90.0, 90.0),
                rng.uniform(-180.0, 180.0),
            )
        )
    return cases


def _interpolate_cases() -> list[tuple[float, ...]]:
    cases: list[tuple[float, ...]] = []
    for fraction in (0.0, 1.0, 0.5, 0.25, 1.0 / 3.0, 0.999999, 1e-9):
        cases.append((fraction, 40.0, -74.0, 40.0, -73.9))
        cases.append((fraction, 40.0, -74.0, 41.0, -73.0))
        cases.append((fraction, -33.9, 151.2, -33.8, 151.3))
        # A shape point repeated: the matcher guards this with approxEquals, and the guard is
        # measured too rather than trusted, because interpolate divides by sin(0) without it.
        cases.append((fraction, 40.0, -74.0, 40.0, -74.0))
    rng = random.Random(20260727)  # noqa: S311 - corpus generation, not cryptography
    for _ in range(200):
        latitude, longitude = rng.uniform(-80.0, 80.0), rng.uniform(-180.0, 180.0)
        cases.append(
            (
                rng.random(),
                latitude,
                longitude,
                latitude + rng.uniform(-0.01, 0.01),
                longitude + rng.uniform(-0.01, 0.01),
            )
        )
    return cases


def _approx_cases() -> list[tuple[float, ...]]:
    cases: list[tuple[float, ...]] = [
        (40.0, -74.0, 40.0, -74.0),
        (40.0, -74.0, 40.0000000001, -74.0),
        (40.0, -74.0, 40.000000000000001, -74.0),
        (0.0, 0.0, 0.0, 0.0),
        (90.0, 0.0, 90.0, 90.0),
    ]
    rng = random.Random(20260728)  # noqa: S311 - corpus generation, not cryptography
    for _ in range(100):
        latitude, longitude = rng.uniform(-90.0, 90.0), rng.uniform(-180.0, 180.0)
        cases.append((latitude, longitude, latitude, longitude))
        cases.append((latitude, longitude, latitude + rng.uniform(-1e-13, 1e-13), longitude))
    return cases


def _run_oracle(lines: list[str], jar: str) -> list[str]:
    payload = "\n".join(lines)
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["javac", "-cp", jar, "-d", work, str(ORACLE)], check=True, capture_output=True
        )
        result = subprocess.run(
            ["java", "-cp", f"{jar}:{work}", ORACLE.stem],
            input=payload,
            check=True,
            capture_output=True,
            text=True,
        )
    return [line for line in result.stdout.split("\n") if line != ""]


def _relative(ours: float, theirs: float) -> float:
    if ours == theirs:
        return 0.0
    scale = max(abs(ours), abs(theirs))
    return abs(ours - theirs) / scale if scale else abs(ours - theirs)


def _report(label: str, differences: list[tuple[tuple, float, float, float]], total: int) -> float:
    """Report the absolute difference alongside the relative one, and return the absolute.

    Relative difference is the wrong yardstick near zero and was actively misleading here: the
    three worst rows on the first run were stops sitting *on* the segment, where the distance is a
    quarter of a millimetre and an absolute difference of 7e-13 m reads as 2.7e-06 relative. The
    absolute column is the one that says how much a reported value can move, so a regression is
    read from it and the relative column is kept only for the values large enough for it to mean
    something.
    """
    worst_absolute = max((abs(entry[1] - entry[2]) for entry in differences), default=0.0)
    # Above unity the two agree, so a relative figure is informative rather than a divide-by-noise.
    large = [entry[3] for entry in differences if max(abs(entry[1]), abs(entry[2])) >= 1.0]
    worst_relative = max(large, default=0.0)
    print(
        f"{label}: {total - len(differences)}/{total} exact,"
        f" worst absolute {worst_absolute:g}, worst relative above 1.0 {worst_relative:g}"
    )
    return worst_absolute


def _check_closest(cases, jar, verbose):
    expected = _run_oracle([f"closest {' '.join(repr(v) for v in case)}" for case in cases], jar)
    latitude_differences = []
    distance_differences = []
    for case, line in zip(cases, expected, strict=True):
        their_lat, their_lng, their_distance = (float(part) for part in line.split())
        stop = to_point(case[0], case[1])
        match = closest_point(stop, to_point(case[2], case[3]), to_point(case[4], case[5]))
        our_lat, our_lng = to_lat_lng_degrees(match)
        our_distance = vector_distance_meters(stop, match)
        for ours, theirs, sink in (
            (our_lat, their_lat, latitude_differences),
            (our_lng, their_lng, latitude_differences),
            (our_distance, their_distance, distance_differences),
        ):
            if ours != theirs:
                sink.append((case, ours, theirs, _relative(ours, theirs)))
            elif verbose:
                print(f"ok   closest {case} -> {theirs}")
    worst_location = _report("closest point, degrees", latitude_differences, len(cases) * 2)
    worst_distance = _report("closest point, metres ", distance_differences, len(cases))
    return max(worst_location, worst_distance)


def _check_interpolate(cases, jar, verbose):
    expected = _run_oracle([f"interp {' '.join(repr(v) for v in case)}" for case in cases], jar)
    differences = []
    for case, line in zip(cases, expected, strict=True):
        their_lat, their_lng = (float(part) for part in line.split())
        point = interpolate(case[0], to_point(case[1], case[2]), to_point(case[3], case[4]))
        our_lat, our_lng = to_lat_lng_degrees(point)
        for ours, theirs in ((our_lat, their_lat), (our_lng, their_lng)):
            # A degenerate edge interpolates to NaN on both sides, which compares unequal to
            # itself. Agreeing on NaN is agreement, and the matcher's approxEquals guard is what
            # keeps a real feed away from it.
            if ours != theirs and not (ours != ours and theirs != theirs):
                differences.append((case, ours, theirs, _relative(ours, theirs)))
            elif verbose:
                print(f"ok   interp {case} -> {theirs}")
    return _report("interpolate, degrees  ", differences, len(cases) * 2)


def _check_approx(cases, jar, verbose):
    expected = _run_oracle([f"approx {' '.join(repr(v) for v in case)}" for case in cases], jar)
    differences = []
    for case, line in zip(cases, expected, strict=True):
        ours = approx_equals(to_point(case[0], case[1]), to_point(case[2], case[3]))
        if ours != (line == "true"):
            differences.append((case, ours, line == "true", 1.0))
        elif verbose:
            print(f"ok   approx {case} -> {line}")
    # A boolean has no last digit to lose, so this one is a pass-or-fail: any disagreement is a
    # port defect rather than a libm difference.
    _report("approxEquals, boolean ", differences, len(cases))
    return differences


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jar", default=DEFAULT_JAR)
    parser.add_argument("--verbose", action="store_true")
    arguments = parser.parse_args()

    worst = max(
        _check_closest(_closest_cases(), arguments.jar, arguments.verbose),
        _check_interpolate(_interpolate_cases(), arguments.jar, arguments.verbose),
    )
    boolean_failures = _check_approx(_approx_cases(), arguments.jar, arguments.verbose)
    for case, ours, theirs, _ in boolean_failures:
        print(f"FAIL approx {case}\n       ours: {ours}\n       s2:   {theirs}")

    print(
        "\nDivergence 12 covers the numeric columns: one ulp of sin inside toPoint, amplified by"
        "\nthe cancellation in a cross product of nearly parallel vectors. Worst absolute"
        f"\ndifference across every column: {worst:g} (degrees for a location, metres for a"
        "\ndistance)."
    )
    # Only the boolean is allowed to fail the build. The numeric columns are a measurement, and
    # a threshold on them would be an invented number rather than a contract.
    return 1 if boolean_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
