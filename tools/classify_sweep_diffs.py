"""Classify a sweep's diffs: divergence-12 float noise against anything real.

Reads the ``*.diff.txt`` files a ``tools/sweep_real_corpus.sh`` run leaves
behind, extracts the unified-diff hunks that ``diff_against_upstream.sh``
printed, and reports one verdict per feed:

- ``MATCH``: no DIVERGENCE marker in the file.
- ``FLOAT_NOISE``: every removed sample pairs with an added sample that is
  JSON-identical up to tiny float differences. That is recorded divergence 12,
  the one-ulp ``sin`` difference inside S2's ``toPoint`` amplified by
  cancellation, measured worst case 2.8e-14 degrees.
- ``REAL``: anything else, with the first non-noise line printed.

This classifies known noise so it cannot bury a new finding; the comparison
itself is untouched and stays as red as it was.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

HUNK = re.compile(r"^\d+(,\d+)?[acd]\d+(,\d+)?$")
# Far above ulp noise (relative 1e-16) and far below any difference a GTFS
# value could carry on purpose, so nothing real can hide inside it.
RTOL = 1e-9
ATOL = 1e-9


def close(ours: object, theirs: object) -> bool:
    # Integers compare exactly: a csvRowNumber or count that differs by one is a
    # real defect however large the values, and only genuine floats carry the
    # divergence-12 arithmetic the tolerance exists for.
    if (
        isinstance(ours, bool)
        or isinstance(theirs, bool)
        or (isinstance(ours, int) and isinstance(theirs, int))
    ):
        return ours == theirs
    if isinstance(ours, (int, float)) and isinstance(theirs, (int, float)):
        return math.isclose(float(ours), float(theirs), rel_tol=RTOL, abs_tol=ATOL)
    if isinstance(ours, list) and isinstance(theirs, list):
        return len(ours) == len(theirs) and all(
            close(a, b) for a, b in zip(ours, theirs, strict=True)
        )
    if isinstance(ours, dict) and isinstance(theirs, dict):
        return ours.keys() == theirs.keys() and all(close(v, theirs[k]) for k, v in ours.items())
    return ours == theirs


def parse_sample(line: str) -> dict | None:
    text = line[1:].strip()
    if not text.startswith("{"):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def classify(path: Path) -> tuple[str, str]:
    lines = path.read_text().splitlines()
    if not any(line.startswith("DIVERGENCE") for line in lines):
        return "MATCH", ""
    ours: list[str] = []
    theirs: list[str] = []
    in_diff = False
    for line in lines:
        if HUNK.match(line):
            in_diff = True
            continue
        if line.startswith("DIVERGENCE"):
            break
        if not in_diff:
            continue
        if line.startswith("<"):
            ours.append(line)
        elif line.startswith(">"):
            theirs.append(line)
    ours_json = [parse_sample(line) for line in ours]
    theirs_json = [parse_sample(line) for line in theirs]
    if None in ours_json or None in theirs_json:
        bad = next(
            line
            for line, sample in zip(ours + theirs, ours_json + theirs_json, strict=True)
            if sample is None
        )
        return "REAL", f"non-sample line differs: {bad.strip()}"
    # Samples are compared as a sorted multiset, and an ulp can reorder the
    # serialised forms, so pair greedily rather than positionally.
    remaining = list(theirs_json)
    for line, sample in zip(ours, ours_json, strict=True):
        match = next((i for i, other in enumerate(remaining) if close(sample, other)), None)
        if match is None:
            return "REAL", f"no float-noise pair for: {line.strip()[:200]}"
        remaining.pop(match)
    if remaining:
        return "REAL", f"unmatched upstream sample: {json.dumps(remaining[0])[:200]}"
    return "FLOAT_NOISE", ""


def main() -> None:
    outdir = Path(sys.argv[1])
    counts: dict[str, int] = {}
    for path in sorted(outdir.glob("*.diff.txt")):
        verdict, detail = classify(path)
        counts[verdict] = counts.get(verdict, 0) + 1
        name = path.name.removesuffix(".diff.txt")
        print(f"{verdict:11} {name}" + (f"  [{detail}]" if detail else ""))
    print("---", " ".join(f"{key}={count}" for key, count in sorted(counts.items())))


if __name__ == "__main__":
    main()
