#!/usr/bin/env python3
"""Differential harness for `gtfs_validator.s2earth` against the S2 classes in the pinned jar.

Nine notice codes report a distance as a context value, so parity level C puts the last digit of
`Double.toString` in the contract. Java's `Math.sin` is specified to within 1 ulp, and CPython's
libm is a different implementation, so agreement is measured here rather than assumed.

The corpus is generated to cover what the rules actually compare: pairs metres apart (the 1.11 m
shape threshold), pairs kilometres apart (transfer distances), the poles and the antimeridian, the
degenerate equal-point case, and a spread of random pairs for the digits in between.

Usage:
    python3 tools/diff_distances_against_s2.py [--jar PATH] [--verbose]
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

from gtfs_validator.s2earth import distance_meters, point_distance_meters

ORACLE = Path(__file__).resolve().parent / "_oracle" / "DumpDistances.java"
# The other `getDistanceMeters` overload, which is a different formula rather than a wrapper.
POINT_ORACLE = Path(__file__).resolve().parent / "_oracle" / "DumpPointDistances.java"
# `gettempdir()` is the per-user directory on macOS, which is not where the jar is kept.
DEFAULT_JAR = os.environ.get("GTFS_JAR", "/tmp/gtfs-validator.jar")  # noqa: S108


def _pairs() -> list[tuple[float, float, float, float]]:
    pairs: list[tuple[float, float, float, float]] = []

    # The degenerate case every shape with a duplicated point hits.
    pairs.append((40.0, -73.0, 40.0, -73.0))

    # Around the 1.11 m threshold that splits two of the four shape-distance codes. One ten
    # thousandth of a degree of latitude is 1.1119510126348764 m, so these straddle it.
    for step in (1e-6, 5e-6, 9e-6, 9.98e-6, 1e-5, 1.01e-5, 2e-5, 1e-4):
        pairs.append((40.0, -73.0, 40.0 + step, -73.0))
        pairs.append((40.0, -73.0, 40.0, -73.0 + step))
        pairs.append((40.0, -73.0, 40.0 + step, -73.0 + step))

    # Transfer and fast-travel distances, which are hundreds of metres to tens of kilometres.
    for degrees in (0.001, 0.01, 0.1, 1.0, 10.0):
        pairs.append((40.0, -73.0, 40.0 + degrees, -73.0))
        pairs.append((40.0, -73.0, 40.0, -73.0 + degrees))

    # Latitude bands, because the longitude term is scaled by cos(lat) at both ends.
    for latitude in (-89.9, -60.0, -23.5, 0.0, 23.5, 60.0, 89.9):
        pairs.append((latitude, 0.0, latitude, 0.01))
        pairs.append((latitude, 179.99, latitude, -179.99))

    # The extremes the guards exist for: poles, the antimeridian, and antipodal points.
    pairs.extend(
        [
            (90.0, 0.0, -90.0, 0.0),
            (90.0, 0.0, 90.0, 180.0),
            (0.0, 0.0, 0.0, 180.0),
            (0.0, 0.0, 0.0, -180.0),
            (-90.0, -180.0, 90.0, 180.0),
            (0.0, 0.0, 0.0, 0.0),
        ]
    )

    # Seeded, so a failure can be quoted in a commit and reproduced.
    rng = random.Random(20260725)  # noqa: S311 - corpus generation, not cryptography
    for _ in range(400):
        pairs.append(
            (
                rng.uniform(-90.0, 90.0),
                rng.uniform(-180.0, 180.0),
                rng.uniform(-90.0, 90.0),
                rng.uniform(-180.0, 180.0),
            )
        )
    # Short random hops, which is what consecutive shape points and stop pairs really look like.
    for _ in range(400):
        latitude, longitude = rng.uniform(-80.0, 80.0), rng.uniform(-180.0, 180.0)
        pairs.append(
            (
                latitude,
                longitude,
                latitude + rng.uniform(-0.01, 0.01),
                longitude + rng.uniform(-0.01, 0.01),
            )
        )
    return pairs


def _run_oracle(
    pairs: list[tuple[float, float, float, float]], jar: str, oracle: Path = ORACLE
) -> list[str]:
    payload = "\n".join(f"{a!r} {b!r} {c!r} {d!r}" for a, b, c, d in pairs)
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["javac", "-cp", jar, "-d", work, str(oracle)], check=True, capture_output=True
        )
        result = subprocess.run(
            ["java", "-cp", f"{jar}:{work}", oracle.stem],
            input=payload,
            check=True,
            capture_output=True,
            text=True,
        )
    return [line for line in result.stdout.split("\n") if line != ""]


def _java_double(value: float) -> str:
    """`Double.toString` for the values these rules produce, which is what Gson writes.

    Java switches to its exponent form at 1e7 and at 1e-3, and always keeps one digit either
    side of the point. Python's repr agrees on the digits but not on the notation, so a
    comparison of strings needs this and a comparison of floats does not. Distances here are
    compared as floats; this exists to report a mismatch in the form the report would show.
    """
    if value == 0.0:
        return "0.0"
    magnitude = abs(value)
    if 1e-3 <= magnitude < 1e7:
        text = repr(value)
        return text if "." in text or "e" in text else text + ".0"
    return repr(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jar", default=DEFAULT_JAR)
    parser.add_argument("--verbose", action="store_true")
    arguments = parser.parse_args()

    pairs = _pairs()
    # Both overloads, because they are different formulas and a rule must use the one its own
    # validator called. Porting only the haversine put a wrong last digit in every
    # transfer-distance notice, and nothing but this comparison would have said so.
    checks = (
        ("S2LatLng haversine", distance_meters, ORACLE),
        ("S2Point angle", point_distance_meters, POINT_ORACLE),
    )
    mismatches = []
    for label, ours_fn, oracle in checks:
        expected = _run_oracle(pairs, arguments.jar, oracle)
        if len(expected) != len(pairs):
            raise SystemExit(f"{label}: oracle returned {len(expected)} for {len(pairs)} pairs")
        mismatches.extend(_compare(pairs, expected, ours_fn, label, arguments.verbose))
    for label, pair, ours, theirs, delta in mismatches:
        print(f"FAIL {label} {pair}\n       ours: {ours}\n       s2:   {theirs}\n       delta: {delta}")
    total = len(pairs) * len(checks)
    print(f"\n{total - len(mismatches)}/{total} distances match the bundled S2 library")
    return 1 if mismatches else 0


def _compare(pairs, expected, ours_fn, label, verbose):
    mismatches = []
    for pair, theirs in zip(pairs, expected, strict=True):
        ours = ours_fn(*pair)
        # Compared as floats, because the two sides render doubles differently above 1e7.
        if ours != float(theirs):
            mismatches.append((label, pair, _java_double(ours), theirs, abs(ours - float(theirs))))
        elif verbose:
            print(f"ok   {label} {pair} -> {theirs}")
    return mismatches


if __name__ == "__main__":
    raise SystemExit(main())
