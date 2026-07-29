#!/usr/bin/env python3
"""Differential harness for `gtfs_validator.farmhash` against the Guava in the pinned jar.

The fingerprint decides the order `StopTimeTravelSpeedValidator` reports its notices in, so
it is a contract in the same way `javahash`'s bucket order is, and it gets a generated corpus
for the same reason: a handful of hand-picked inputs tests what the port already does.

The corpus crosses every boundary the implementation branches on. Guava splits the input at
16, 32 and 64 bytes, the long path consumes 64 bytes a turn and re-reads an overlapping tail,
and the short paths branch again at 8 and 4 bytes and on empty. Lengths on and around each of
those are enumerated rather than sampled, because an off-by-one in a load is exactly the
defect this catches: the first transcription here read one of its terms eight bytes late, and
that agreed with Guava on every length except 33 to 64.

The second mode checks the other half, which is Guava's `Hasher` rather than the hash: the
byte stream `putInt` and `putUnencodedChars` build, over ids holding non-ASCII and non-BMP
characters, where UTF-16 code units and UTF-8 bytes disagree. It calls the rules' own
`trip_fingerprint` rather than a copy of it, so a change to the production path cannot leave
this passing.

Usage:
    python3 tools/diff_farmhash_against_guava.py [--jar PATH] [--verbose]
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

from gtfs_validator.farmhash import fingerprint64
from gtfs_validator.rules._shared.travel_speed import trip_fingerprint

ORACLE = Path(__file__).resolve().parent / "_oracle" / "DumpFarmHash.java"
# Every branch boundary, and one either side of it. 0 is its own case, 65 and 129 are the
# first lengths to enter and to repeat the 64-byte loop, and 128 is the only multiple of 64
# in range where the loop's tail does not overlap what it already read.
_BOUNDARIES = (
    0,
    1,
    2,
    3,
    4,
    5,
    7,
    8,
    9,
    15,
    16,
    17,
    24,
    31,
    32,
    33,
    48,
    63,
    64,
    65,
    66,
    127,
    128,
    129,
    191,
    192,
    193,
    256,
    257,
)
_SAMPLES_PER_LENGTH = 6
# Ids chosen so that UTF-16 code units and UTF-8 bytes disagree: a BMP non-ASCII character is
# two bytes in UTF-8 and one code unit, and an emoji is four bytes and two code units.
_TRIP_IDS = ("", "A", "STOP_1", "Ünïcödé", "🚉", "🚉A", "S" * 40)


def byte_corpus(seed: int = 11) -> list[bytes]:
    rng = random.Random(seed)  # noqa: S311 - corpus generation, not cryptography
    corpus: list[bytes] = []
    for length in _BOUNDARIES:
        for _ in range(_SAMPLES_PER_LENGTH):
            corpus.append(bytes(rng.randrange(256) for _ in range(length)))
        # A structured input as well as random ones, each byte its own position mod 256, so a
        # load from the wrong offset reads a value that says which offset it came from. Random
        # bytes can agree by accident; these cannot. The earlier spelling described this as "a
        # run of equal bytes", which is what it is not, and fell back to `bytes(length)` above
        # 255 bytes, which is all zeros: precisely the input that hides a misread offset.
        corpus.append(bytes(index % 256 for index in range(length)))
    return corpus


def trip_corpus(seed: int = 12) -> list[tuple[str, list[tuple[str, int, int]]]]:
    """Trips as the validator fingerprints them: a route id and its stop pattern."""
    rng = random.Random(seed)  # noqa: S311 - corpus generation, not cryptography
    trips: list[tuple[str, list[tuple[str, int, int]]]] = []
    for route_id in _TRIP_IDS:
        for stop_count in (0, 1, 2, 5, 17):
            stop_times = [
                (
                    _TRIP_IDS[rng.randrange(len(_TRIP_IDS))],
                    rng.randrange(0, 100000),
                    rng.randrange(0, 100000),
                )
                for _ in range(stop_count)
            ]
            trips.append((route_id, stop_times))
    return trips


def _run_oracle(jar: str, mode: str, lines: list[str], work: str) -> list[int]:
    subprocess.run(
        ["javac", "-cp", jar, "-d", work, str(ORACLE)],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["java", "-cp", f"{work}:{jar}", "DumpFarmHash", mode],
        input="\n".join(lines) + "\n",
        text=True,
        check=True,
        capture_output=True,
    )
    return [int(line) for line in result.stdout.splitlines()]


def main() -> int:
    parser = argparse.ArgumentParser()
    # `gettempdir()` is the per-user directory on macOS, which is not where the jar is kept.
    parser.add_argument("--jar", default=os.environ.get("GTFS_JAR", "/tmp/gtfs-validator.jar"))  # noqa: S108
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    failures = 0
    with tempfile.TemporaryDirectory() as work:
        corpus = byte_corpus()
        expected = _run_oracle(args.jar, "bytes", [data.hex() for data in corpus], work)
        for data, want in zip(corpus, expected, strict=True):
            got = fingerprint64(data)
            if got != want:
                failures += 1
                print(f"bytes len={len(data)}: guava {want}, ours {got}", file=sys.stderr)
            elif args.verbose:
                print(f"bytes len={len(data)}: {got}")

        trips = trip_corpus()
        lines = [
            "{}|{}".format(
                route_id.encode("utf-8").hex(),
                ";".join(
                    f"{stop_id.encode('utf-8').hex()},{arrival},{departure}"
                    for stop_id, arrival, departure in stop_times
                ),
            )
            for route_id, stop_times in trips
        ]
        expected = _run_oracle(args.jar, "trip", lines, work)
        for (route_id, stop_times), want in zip(trips, expected, strict=True):
            rows = [
                {"stop_id": stop_id, "arrival_time": arrival, "departure_time": departure}
                for stop_id, arrival, departure in stop_times
            ]
            got = trip_fingerprint(route_id, rows)
            if got != want:
                failures += 1
                print(
                    f"trip route={route_id!r} stops={len(stop_times)}: guava {want}, ours {got}",
                    file=sys.stderr,
                )
            elif args.verbose:
                print(f"trip route={route_id!r} stops={len(stop_times)}: {got}")

    total = len(corpus) + len(trips)
    print(f"{total - failures}/{total} agree with Guava")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
