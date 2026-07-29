#!/usr/bin/env python3
"""Differential the Python geometry engine against the JTS inside the pinned jar.

`invalid_geometry` reports JTS's own error wording, so parity needs the *same error* for
the same shape, not merely the same verdict. Probing through feeds costs a JVM per shape
and covers a handful; this runs a whole corpus through one JVM and compares every verdict.

The corpus is deterministic: a fixed seed, so a mismatch is reproducible and a clean run
means something. Random shapes are the point, because the errors this has to get right
(which of two competing errors wins, a crossing against a touch) are exactly what a
hand-built corpus keeps missing.

Usage:
    tools/diff_geometry_against_jts.py                 # the built-in corpus
    tools/diff_geometry_against_jts.py --random 2000   # plus random shapes
    tools/diff_geometry_against_jts.py --seed 7 --random 500

Exits non-zero on the first mismatch, printing the shape so it can be pasted straight
into tools/jts/CheckPolygons.java's stdin.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gtfs_validator.geometry.validity import (  # noqa: E402
    polygon_construction_message,
    validate_multipolygon,
    validate_polygon,
)

CHECKER = ROOT / "tools" / "jts" / "CheckPolygons.java"

# Shapes that each isolate one error, or make two compete. Kept in the tool rather than a
# fixture file so the corpus and the comparison stay in one place.
CURATED: dict[str, str] = {
    "square": "0,0 4,0 4,4 0,4 0,0",
    "square_cw": "0,0 0,4 4,4 4,0 0,0",
    "triangle3pt": "0,0 1,0 0,0",
    "triangle4pt": "0,0 1,0 1,1 0,0",
    "repeated_pt": "0,0 4,0 4,0 4,4 0,4 0,0",
    "collapsed": "0,0 1,1 1,1 0,0",
    "bowtie": "0,0 2,2 2,0 0,2 0,0",
    "figure8_touch": "0,0 2,0 1,1 2,2 0,2 1,1 0,0",
    "spike": "0,0 4,0 4,4 2,2 4,4 0,4 0,0",
    "zero_area_shell": "0,0 5,0 0,0 5,0 0,0",
    "line_shell": "0,0 1,0 2,0 0,0",
    "hole_ok": "0,0 10,0 10,10 0,10 0,0;2,2 4,2 4,4 2,4 2,2",
    "hole_outside": "0,0 4,0 4,4 0,4 0,0;10,10 11,10 11,11 10,10",
    "hole_crossing_shell": "0,0 4,0 4,4 0,4 0,0;3,3 6,3 6,6 3,6 3,3",
    "nested_holes": "0,0 10,0 10,10 0,10 0,0;1,1 8,1 8,8 1,8 1,1;2,2 7,2 7,7 2,7 2,2",
    "holes_touch_once": "0,0 10,0 10,10 0,10 0,0;1,1 5,1 5,5 1,5 1,1;5,5 9,5 9,9 5,9 5,5",
    "holes_split_interior": "0,0 10,0 10,10 0,10 0,0;0,0 5,0 5,10 0,10 0,0;5,0 10,0 10,10 5,10 5,0",
    "hole_equals_shell": "0,0 4,0 4,4 0,4 0,0;0,0 4,0 4,4 0,4 0,0",
    "duplicate_holes": "0,0 10,0 10,10 0,10 0,0;1,1 3,1 3,3 1,3 1,1;1,1 3,1 3,3 1,3 1,1",
    "hole_pinches_two_points": "0,0 10,0 10,10 0,10 0,0;0,5 5,4 10,5 5,6 0,5",
    "hole_touch_one_point": "0,0 10,0 10,10 0,10 0,0;0,5 5,4 5,6 0,5",
    "two_holes_pinch": "0,0 10,0 10,10 0,10 0,0;0,1 4,1 4,9 0,9 0,1;4,1 10,1 10,9 4,9 4,1",
    "hole_touch_segment": "0,0 10,0 10,10 0,10 0,0;0,2 0,8 4,8 4,2 0,2",
    "hole_shares_corner": "0,0 10,0 10,10 0,10 0,0;0,0 4,0 4,4 0,4 0,0",
    "three_nested_holes": (
        "0,0 20,0 20,20 0,20 0,0;1,1 18,1 18,18 1,18 1,1;2,2 17,2 17,17 2,17 2,2;"
        "3,3 16,3 16,16 3,16 3,3"
    ),
    "hole_fewpoints": "0,0 10,0 10,10 0,10 0,0;1,1 2,2 2,2 1,1",
    "nan_mid": "0,0 4,0 NaN,4 0,4 0,0",
    "inf_mid": "0,0 4,0 Infinity,4 0,4 0,0",
    "nan_and_bowtie": "0,0 2,2 NaN,0 0,2 0,0",
    "bowtie_and_hole_outside": "0,0 2,2 2,0 0,2 0,0;20,20 21,20 21,21 20,20",
    "fewpoints_and_holeoutside": "0,0 1,1 1,1 0,0;20,20 21,20 21,21 20,20",
    "mp_disjoint": "0,0 1,0 1,1 0,1 0,0#5,5 6,5 6,6 5,6 5,5",
    "mp_nested": "0,0 10,0 10,10 0,10 0,0#2,2 4,2 4,4 2,4 2,2",
    "mp_overlap": "0,0 4,0 4,4 0,4 0,0#2,2 6,2 6,6 2,6 2,2",
    "mp_touch_edge": "0,0 2,0 2,2 0,2 0,0#2,0 4,0 4,2 2,2 2,0",
    "mp_duplicate": "0,0 2,0 2,2 0,2 0,0#0,0 2,0 2,2 0,2 0,0",
    "mp_shell_in_hole": "0,0 10,0 10,10 0,10 0,0;2,2 8,2 8,8 2,8 2,2#3,3 7,3 7,7 3,7 3,3",
    "mp_first_invalid": "0,0 2,2 2,0 0,2 0,0#5,5 6,5 6,6 5,6 5,5",
    "mp_second_invalid": "0,0 1,0 1,1 0,1 0,0#5,5 7,7 7,5 5,7 5,5",
    "mp_nan": "0,0 1,0 1,1 0,1 0,0#5,5 NaN,5 6,6 5,6 5,5",
    "empty_shell_with_hole": "EMPTY;2,2 3,2 2,2",
    "empty_shell_alone": "EMPTY",
    "empty_hole": "0,0 4,0 4,4 0,4 0,0;EMPTY",
    "nan_closed": "NaN,0 1,0 1,1 NaN,0",
    "figure8_plus_hole_outside": "0,0 2,0 1,1 2,2 0,2 1,1 0,0;10,10 11,10 10,11 10,10",
    "two_holes_share_only_that_point": "0,0 10,0 10,10 0,10 0,0;5,0 3,4 4,4 5,0;5,0 6,4 7,4 5,0",
    "star_four_holes_one_point": (
        "0,0 10,0 10,10 0,10 0,0;5,5 1,4 1,6 5,5;5,5 9,4 9,6 5,5;5,5 4,1 6,1 5,5"
    ),
    "chain_three_holes": "0,0 20,0 20,20 0,20 0,0;2,2 6,2 4,6 2,2;6,2 10,2 8,6 6,2;10,2 14,2 12,6 10,2",
    "hole_touches_shell_twice_same_pt": "0,0 10,0 10,10 0,10 0,0;5,0 3,4 5,0 7,4 5,0",
    "mp_hole_outside_then_nested": "0,0 4,0 4,4 0,4 0,0;10,10 11,10 11,11 10,10#0,0 4,0 4,4 0,4 0,0",
}


def random_shapes(count: int, seed: int) -> dict[str, str]:
    """Small-integer coordinates, so touching and collinearity actually happen.

    Floats spread over a wide range make degenerate cases vanishingly rare, and the
    degenerate cases are the ones where the two implementations can disagree.
    """
    # Reproducibility is the requirement here, not unpredictability: a corpus generator
    # wants the same shapes every run so a mismatch can be re-run.
    rng = random.Random(seed)  # noqa: S311
    shapes: dict[str, str] = {}
    for index in range(count):
        rings = []
        for _ in range(rng.choice([1, 1, 1, 2, 2, 3])):
            length = rng.choice([3, 4, 4, 5, 5, 6])
            points = [(rng.randint(0, 6), rng.randint(0, 6)) for _ in range(length)]
            points.append(points[0])
            rings.append(" ".join(f"{x},{y}" for x, y in points))
        members = [";".join(rings)]
        if rng.random() < 0.25:
            length = rng.choice([4, 5])
            points = [(rng.randint(0, 6), rng.randint(0, 6)) for _ in range(length)]
            points.append(points[0])
            members.append(" ".join(f"{x},{y}" for x, y in points))
        shapes[f"rand{index}"] = "#".join(members)
    return shapes


def parse_shape(text: str) -> list[list[list[tuple[float, float]]]]:
    members = []
    for member in text.split("#"):
        rings = []
        for ring in member.split(";"):
            points = []
            if ring.strip() == "EMPTY":
                rings.append(points)
                continue
            for token in ring.split():
                x, _, y = token.partition(",")
                points.append((float(x), float(y)))
            rings.append(points)
        members.append(rings)
    return members


def our_verdict(text: str, messages: dict) -> str:
    """The verdict in the oracle's own format, so the two are compared as strings."""
    members = parse_shape(text)
    for member in members:
        message = polygon_construction_message(member)
        if message is not None:
            return f"THROWS\t{message}"
    error = validate_polygon(members[0]) if len(members) == 1 else validate_multipolygon(members)
    if error is None:
        return "VALID"
    return f"{CODES[error]}\t{messages[error]}"


# TopologyValidationError's numeric codes, for comparing against the oracle's output.
CODES = {
    "TOPOLOGY_VALIDATION_ERROR": 0,
    "REPEATED_POINT": 1,
    "HOLE_OUTSIDE_SHELL": 2,
    "NESTED_HOLES": 3,
    "DISCONNECTED_INTERIOR": 4,
    "SELF_INTERSECTION": 5,
    "RING_SELF_INTERSECTION": 6,
    "NESTED_SHELLS": 7,
    "DUPLICATE_RINGS": 8,
    "TOO_FEW_POINTS": 9,
    "INVALID_COORDINATE": 10,
    "RING_NOT_CLOSED": 11,
}


def jts_verdicts(shapes: dict[str, str], jar: Path) -> dict[str, str]:
    payload = "".join(f"{name}|{shape}\n" for name, shape in shapes.items())
    result = subprocess.run(
        ["java", "-cp", str(jar), str(CHECKER)],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    verdicts = {}
    for line in result.stdout.splitlines():
        name, _, verdict = line.partition("\t")
        verdicts[name] = verdict
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=Path("/private/tmp/gtfs-validator.jar"))
    parser.add_argument("--random", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260725)
    parser.add_argument("--limit", type=int, default=20, help="mismatches to print")
    args = parser.parse_args()

    messages = json.loads(files("gtfs_validator.data").joinpath("jts_messages.json").read_text())
    table = messages["topology_errors"]

    shapes = dict(CURATED)
    if args.random:
        shapes.update(random_shapes(args.random, args.seed))

    oracle = jts_verdicts(shapes, args.jar)
    mismatches = []
    for name, shape in shapes.items():
        expected = oracle.get(name, "MISSING")
        actual = our_verdict(shape, table)
        if expected != actual:
            mismatches.append((name, shape, expected, actual))

    print(f"compared {len(shapes)} shapes, {len(mismatches)} mismatches")
    for name, shape, expected, actual in mismatches[: args.limit]:
        print(f"\n{name}|{shape}\n  jts: {expected}\n  ours: {actual}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
