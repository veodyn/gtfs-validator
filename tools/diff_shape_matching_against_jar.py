#!/usr/bin/env python3
"""Differential harness for the local-minimum search behind the stop-to-shape codes.

`ShapePoints.matchesFromLocation` produces two things that are not reported numbers and so are not
covered by divergence 12's "last digit" verdict:

* **The candidate count.** It is what `stop_has_too_many_matches_for_shape` reports and compares
  against its threshold of 20, and it is the set the assignment search runs over. A different count
  is a notice appearing or vanishing.
* **Which candidate is closest.** `Collections.min` over the candidates picks the match that the
  too-many-matches and out-of-order notices *report*, so a different argmin is a different reported
  location and shape index for the same finding.

Both can turn on the eleventh digit, because both are decided by comparing two distances that are
nearly equal when a stop sits almost above a shape vertex. This harness measures how often, over a
corpus of the geometries the matcher actually meets.

Usage:
    python3 tools/diff_shape_matching_against_jar.py [--jar PATH] [--verbose]
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

from gtfs_validator.s2point import to_point
from gtfs_validator.stop_to_shape.shape import ShapePoints

ORACLE = Path(__file__).resolve().parent / "_oracle" / "DumpShapeMatches.java"
# `gettempdir()` is the per-user directory on macOS, which is not where the jar is kept.
DEFAULT_JAR = os.environ.get("GTFS_JAR", "/tmp/gtfs-validator.jar")  # noqa: S108
MAX_DISTANCE = 100.0


def _cases() -> list[tuple[float, tuple[float, float], list[tuple[float, float]]]]:
    """(max distance, stop, shape points) triples."""
    cases = []

    # A stop directly above a shape vertex, which is the geometry that splits one apparent local
    # minimum into two: the perpendicular foot on the segment before the vertex is a hair closer
    # than the vertex itself, so the loop sees the shape receding and banks a match.
    straight = [(40.0, -74.0 + step * 0.001) for step in range(5)]
    cases.append((MAX_DISTANCE, (40.0005, -73.998), straight))
    cases.append((MAX_DISTANCE, (40.0005, -73.9985), straight))
    cases.append((MAX_DISTANCE, (40.0, -73.998), straight))

    # Excursions, one candidate each: this is the shape a too-many-matches fixture needs.
    for visits in (3, 20, 21, 25):
        points = []
        for visit in range(visits):
            points.append((40.0, -74.0 + visit * 0.000001))
            points.append((40.01, -74.0 + visit * 0.001))
            points.append((40.01, -74.0 + visit * 0.001 + 0.0005))
        cases.append((MAX_DISTANCE, (40.0, -74.0), points))

    # A stop beyond the end of a shape, and one beside a single segment.
    cases.append((MAX_DISTANCE, (40.0, -74.1), [(40.0, -74.0), (40.0, -73.99)]))
    cases.append((MAX_DISTANCE, (40.0005, -73.995), [(40.0, -74.0), (40.0, -73.99)]))

    # A shape with a repeated point, which sends robustCrossProd down its ortho fallback.
    cases.append((MAX_DISTANCE, (40.0005, -73.995), [(40.0, -74.0), (40.0, -74.0), (40.0, -73.99)]))

    # Seeded, so a failure can be quoted in a commit and reproduced.
    rng = random.Random(20260726)  # noqa: S311 - corpus generation, not cryptography
    for _ in range(150):
        latitude, longitude = rng.uniform(-70.0, 70.0), rng.uniform(-180.0, 180.0)
        points = [(latitude, longitude)]
        for _ in range(rng.randint(2, 8)):
            points.append(
                (
                    points[-1][0] + rng.uniform(-0.002, 0.002),
                    points[-1][1] + rng.uniform(-0.002, 0.002),
                )
            )
        # Half the stops are placed on a vertex, which is where the two sides can disagree.
        if rng.random() < 0.5:
            vertex = points[rng.randrange(len(points))]
            stop = (vertex[0] + rng.uniform(-0.0006, 0.0006), vertex[1])
        else:
            stop = (latitude + rng.uniform(-0.001, 0.001), longitude + rng.uniform(-0.001, 0.001))
        cases.append((MAX_DISTANCE, stop, points))
    return cases


def _run_oracle(cases, jar: str) -> list[tuple[int, list[tuple[int, float]]]]:
    lines = []
    for max_distance, stop, points in cases:
        coordinates = " ".join(f"{lat!r} {lon!r}" for lat, lon in points)
        lines.append(f"{max_distance!r} {stop[0]!r} {stop[1]!r} {coordinates}")
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["javac", "-cp", jar, "-d", work, str(ORACLE)], check=True, capture_output=True
        )
        result = subprocess.run(
            ["java", "-cp", f"{jar}:{work}", ORACLE.stem],
            input="\n".join(lines),
            check=True,
            capture_output=True,
            text=True,
        )
    parsed = []
    for line in result.stdout.strip().split("\n"):
        fields = line.split()
        matches = []
        for field in fields[1:]:
            index, distance = field.split(":")
            matches.append((int(index), float(distance)))
        parsed.append((int(fields[0]), matches))
    return parsed


def _ours(case) -> tuple[int, list[tuple[int, float]]]:
    max_distance, stop, points = case
    shape = ShapePoints.from_rows(
        [
            {"shape_pt_lat": lat, "shape_pt_lon": lon, "shape_pt_sequence": index + 1}
            for index, (lat, lon) in enumerate(points)
        ]
    )
    matches = shape.matches_from_location(to_point(*stop), max_distance)
    return len(matches), [(match.index, match.geo_distance_to_shape) for match in matches]


def _argmin(matches: list[tuple[int, float]]) -> int | None:
    """The index `Collections.min` would pick, keeping the first of a tie."""
    if not matches:
        return None
    best = 0
    for position in range(1, len(matches)):
        if matches[position][1] < matches[best][1]:
            best = position
    return matches[best][0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jar", default=DEFAULT_JAR)
    parser.add_argument("--verbose", action="store_true")
    arguments = parser.parse_args()

    cases = _cases()
    expected = _run_oracle(cases, arguments.jar)
    count_mismatches = []
    argmin_mismatches = []
    for case, (their_count, their_matches) in zip(cases, expected, strict=True):
        our_count, our_matches = _ours(case)
        if our_count != their_count:
            count_mismatches.append((case, our_count, their_count))
        elif _argmin(our_matches) != _argmin(their_matches):
            argmin_mismatches.append((case, our_matches, their_matches))
        elif arguments.verbose:
            print(f"ok   {case[1]} -> {our_count} matches")

    for case, ours, theirs in count_mismatches:
        print(
            f"COUNT stop={case[1]} points={len(case[2])}\n       ours: {ours}\n       jar:  {theirs}"
        )
    for case, ours, theirs in argmin_mismatches:
        print(f"ARGMIN stop={case[1]}\n       ours: {ours}\n       jar:  {theirs}")

    total = len(cases)
    print(
        f"\n{total - len(count_mismatches)}/{total} candidate counts agree, "
        f"{total - len(count_mismatches) - len(argmin_mismatches)}/{total} also agree on which "
        "candidate is closest"
    )
    # The count is control flow, so a disagreement there is reported as a failure. The argmin is
    # reported too: it decides a notice's location, and divergence 12 is why it can move.
    return 1 if count_mismatches or argmin_mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
