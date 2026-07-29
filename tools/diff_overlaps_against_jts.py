#!/usr/bin/env python3
"""Differential `geometry.overlaps` against the JTS inside the pinned jar.

`overlaps` is a DE-9IM predicate, so the cases that decide it are the degenerate ones: a
shared edge, a shared vertex, one polygon inside another and touching its boundary, a hole that
the other polygon reaches into. A hand-built corpus of "clearly overlapping" and "clearly not"
shapes tests the easy half and nothing else, which is why this generates squares and triangles
on a small integer lattice: on a coarse grid, shapes collide on their edges and vertices
constantly, and every such collision is a case JTS decides by rule rather than by margin.

Usage:
    tools/diff_overlaps_against_jts.py                # the built-in corpus
    tools/diff_overlaps_against_jts.py --random 3000  # plus random lattice pairs
    tools/diff_overlaps_against_jts.py --seed 7 --random 500 --verbose
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gtfs_validator.geometry.overlaps import polygons_overlap, to_exact  # noqa: E402

ORACLE = ROOT / "tools" / "jts" / "CheckOverlaps.java"


def square(x: float, y: float, size: float) -> list[list[list[float]]]:
    return [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]]


def with_hole(x: float, y: float, size: float, hole: float) -> list[list[list[float]]]:
    """A square with a square hole in the middle, wound the other way as GeoJSON asks."""
    inset = (size - hole) / 2
    hx, hy = x + inset, y + inset
    return [
        square(x, y, size)[0],
        [[hx, hy], [hx, hy + hole], [hx + hole, hy + hole], [hx + hole, hy], [hx, hy]],
    ]


def triangle(x: float, y: float, size: float) -> list[list[list[float]]]:
    return [[[x, y], [x + size, y], [x, y + size], [x, y]]]


def shell_with_hole(hole: list[list[float]], size: float = 10.0) -> list[list[list[float]]]:
    """A fixed 10x10 shell with the given hole, for the pairs that share a shell.

    These are the shapes a boundary-only predicate cannot decide. Two polygons with the same
    shell and holes in different corners have every part of each boundary inside the other's
    closure, and still overlap, because each reaches area the other punches out. That was a real
    defect here and it survived 3,017 random pairs, because random pairs have no holes.
    """
    return [square(0.0, 0.0, size)[0], hole]


CORNER_HOLE = [[1.0, 1.0], [1.0, 3.0], [3.0, 3.0], [3.0, 1.0], [1.0, 1.0]]
FAR_CORNER_HOLE = [[7.0, 7.0], [7.0, 9.0], [9.0, 9.0], [9.0, 7.0], [7.0, 7.0]]
OVERLAPPING_HOLE = [[2.0, 2.0], [2.0, 4.0], [4.0, 4.0], [4.0, 2.0], [2.0, 2.0]]


def named_corpus() -> dict[str, tuple[list, list]]:
    """The cases worth naming, each one a rule rather than a margin."""
    unit = square(0.0, 0.0, 2.0)
    return {
        "identical": (unit, square(0.0, 0.0, 2.0)),
        "disjoint": (unit, square(5.0, 5.0, 2.0)),
        "shared-edge": (unit, square(2.0, 0.0, 2.0)),
        "shared-vertex": (unit, square(2.0, 2.0, 2.0)),
        "properly-crossing": (unit, square(1.0, 1.0, 2.0)),
        "contained": (unit, square(0.5, 0.5, 1.0)),
        "contained-touching-edge": (unit, square(0.0, 0.5, 1.0)),
        "contains": (square(0.5, 0.5, 1.0), unit),
        "half-overlap-band": (
            unit,
            [[[1.0, -1.0], [3.0, -1.0], [3.0, 3.0], [1.0, 3.0], [1.0, -1.0]]],
        ),
        "triangle-crossing": (unit, triangle(1.0, 1.0, 2.0)),
        "triangle-inside": (unit, triangle(0.25, 0.25, 0.5)),
        "hole-vs-inner": (with_hole(0.0, 0.0, 6.0, 2.0), square(2.5, 2.5, 1.0)),
        "hole-vs-crossing": (with_hole(0.0, 0.0, 6.0, 2.0), square(1.0, 2.5, 2.0)),
        "hole-edge-shared": (with_hole(0.0, 0.0, 6.0, 2.0), square(2.0, 2.0, 2.0)),
        "hole-vs-hole": (with_hole(0.0, 0.0, 6.0, 2.0), with_hole(1.0, 1.0, 6.0, 2.0)),
        "sliver-crossing": (unit, [[[1.0, 0.5], [5.0, 0.5], [5.0, 0.6], [1.0, 0.6], [1.0, 0.5]]]),
        "collinear-partial-edge": (
            unit,
            [[[0.5, 2.0], [1.5, 2.0], [1.5, 4.0], [0.5, 4.0], [0.5, 2.0]]],
        ),
        # Same shell, holes elsewhere. Neither boundary ever leaves the other's closure, and both
        # reach area the other excludes, so these are the cases a boundary walk answers wrongly.
        "same-shell-holes-apart": (shell_with_hole(CORNER_HOLE), shell_with_hole(FAR_CORNER_HOLE)),
        "same-shell-holes-overlapping": (
            shell_with_hole(CORNER_HOLE),
            shell_with_hole(OVERLAPPING_HOLE),
        ),
        "same-shell-same-hole": (shell_with_hole(CORNER_HOLE), shell_with_hole(list(CORNER_HOLE))),
        "same-shell-one-hole": (shell_with_hole(CORNER_HOLE), square(0.0, 0.0, 10.0)),
        "hole-filled-by-other": (shell_with_hole(CORNER_HOLE), square(1.0, 1.0, 2.0)),
    }


def random_corpus(count: int, seed: int) -> dict[str, tuple[list, list]]:
    """Pairs on a small lattice, where edge and vertex collisions are the common case.

    A third of the shapes carry a hole, which the first version of this generator did not. That
    omission is why 3,000 clean cases certified a predicate answering the same-shell-with-holes
    pair backwards: no random shape had a hole, so no random pair could reach area through one.
    """
    rng = random.Random(seed)  # noqa: S311 - corpus generation, not cryptography
    cases: dict[str, tuple[list, list]] = {}
    for index in range(count):
        cases[f"random-{index}"] = (_random_shape(rng), _random_shape(rng))
    return cases


def _random_shape(rng: random.Random) -> list[list[list[float]]]:
    """A triangle, a square, or a square with a hole strictly inside it."""
    kind = rng.randrange(3)
    x, y = float(rng.randrange(0, 4)), float(rng.randrange(0, 4))
    if kind == 0:
        return triangle(x, y, float(rng.randrange(1, 4)))
    size = float(rng.randrange(1, 5))
    if kind == 1:
        return square(x, y, size)
    # The hole is a quarter of the side and offset by a quarter, so it never touches the shell:
    # JTS refuses a hole meeting the shell along an edge, and such a pair would be skipped as
    # unbuildable rather than compared.
    quarter = size / 4
    hx, hy = x + quarter, y + quarter
    hole = [
        [hx, hy],
        [hx, hy + quarter],
        [hx + quarter, hy + quarter],
        [hx + quarter, hy],
        [hx, hy],
    ]
    return [square(x, y, size)[0], hole]


def _ring_text(ring: list[list[float]]) -> str:
    return " ".join(f"{x},{y}" for x, y in ring)


def _polygon_text(rings: list[list[list[float]]]) -> str:
    return ";".join(_ring_text(ring) for ring in rings)


def run_oracle(cases: dict[str, tuple[list, list]], jar: str) -> dict[str, str]:
    names = list(cases)
    payload = "\n".join(
        f"{name}|{_polygon_text(cases[name][0])}#{_polygon_text(cases[name][1])}" for name in names
    )
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["javac", "-cp", jar, "-d", work, str(ORACLE)], check=True, capture_output=True
        )
        result = subprocess.run(
            ["java", "-cp", f"{work}:{jar}", "CheckOverlaps"],
            input=payload + "\n",
            text=True,
            check=True,
            capture_output=True,
        )
    verdicts = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        verdicts[parts[0]] = parts[1] if len(parts) > 1 else "?"
    return verdicts


def main() -> int:
    parser = argparse.ArgumentParser()
    # `gettempdir()` is the per-user directory on macOS, which is not where the jar is kept.
    parser.add_argument("--jar", default=os.environ.get("GTFS_JAR", "/tmp/gtfs-validator.jar"))  # noqa: S108
    parser.add_argument("--random", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    cases = named_corpus()
    cases.update(random_corpus(args.random, args.seed))
    expected = run_oracle(cases, args.jar)

    failures = 0
    skipped = 0
    for name, (first, second) in cases.items():
        want = expected.get(name, "?")
        if want == "THROWS":
            # An invalid ring JTS refuses to build. Not this predicate's business.
            skipped += 1
            continue
        ours = "TRUE" if polygons_overlap(to_exact(first), to_exact(second)) else "FALSE"
        if ours != want:
            failures += 1
            print(f"FAIL {name}: jts {want}, ours {ours}", file=sys.stderr)
            print(f"       A: {_polygon_text(first)}", file=sys.stderr)
            print(f"       B: {_polygon_text(second)}", file=sys.stderr)
        elif args.verbose:
            print(f"ok   {name}: {ours}")

    total = len(cases) - skipped
    print(f"{total - failures}/{total} agree with JTS ({skipped} skipped as unbuildable)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
