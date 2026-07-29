#!/usr/bin/env python3
"""Differential harness for `gtfs_validator.javahash` against the pinned JDK's HashMap.

`hashmap_order` decides which notices survive the 1,000-sample cap for every rule that
collects into a `HashMap` and iterates `keySet()`. That makes iteration order a contract,
and a contract is worth a corpus rather than a handful of probes: the locale port passed
its own 17-tag corpus while two behaviours were wrong, because a corpus assembled from
what comes to mind tests what the implementation already does.

So the corpora are generated to cross the thresholds the implementation must know about,
whether or not it currently does. They live in `_hashmap_corpora.py`, which is where to look
to see what is covered; this file is the three oracles and the comparison.

Usage:
    python3 tools/diff_hashmap_against_jdk.py [--verbose]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _hashmap_corpora import long_corpora, string_corpora

from gtfs_validator.javahash import hashmap_order, long_multimap_order, multimap_order

ORACLE = Path(__file__).resolve().parent / "_oracle" / "DumpHashOrder.java"
# The second oracle needs Guava, so it compiles against the jar rather than the bare JDK.
MULTIMAP_ORACLE = Path(__file__).resolve().parent / "_oracle" / "DumpMultimapOrder.java"
# The third takes Long keys, which hash and compare differently from strings.
LONG_ORACLE = Path(__file__).resolve().parent / "_oracle" / "DumpLongMultimapOrder.java"


def _run_long_oracle(cases: dict[str, list[int]], jar: str) -> dict[str, list[int]]:
    names = list(cases)
    payload = "\n---\n".join("\n".join(str(key) for key in cases[name]) for name in names)
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["javac", "-cp", jar, "-d", work, str(LONG_ORACLE)],
            check=True,
            capture_output=True,
        )
        result = subprocess.run(
            ["java", "-cp", f"{jar}:{work}", "DumpLongMultimapOrder"],
            input=payload,
            check=True,
            capture_output=True,
            text=True,
        )
    groups = result.stdout.split("---\n")
    if len(groups) != len(names):
        raise SystemExit(f"long oracle returned {len(groups)} groups for {len(names)} cases")
    return {
        name: [int(line) for line in group.split("\n") if line.strip()]
        for name, group in zip(names, groups, strict=True)
    }


def _run_multimap_oracle(cases: dict[str, list[str]], jar: str) -> dict[str, list[str]]:
    """Guava's `ArrayListMultimap` key order, which is not a plain `HashMap`'s.

    Compiled against the pinned jar so the Guava is the one upstream links rather than whatever
    a rebuild would resolve to.
    """
    names = list(cases)
    payload = "\n---\n".join("\n".join("K" + _escape(key) for key in cases[name]) for name in names)
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["javac", "-cp", jar, "-d", work, str(MULTIMAP_ORACLE)],
            check=True,
            capture_output=True,
        )
        result = subprocess.run(
            ["java", "-cp", f"{jar}:{work}", "DumpMultimapOrder"],
            input=payload,
            check=True,
            capture_output=True,
            text=True,
        )
    groups = result.stdout.split("---\n")
    if len(groups) != len(names):
        raise SystemExit(f"multimap oracle returned {len(groups)} groups for {len(names)} cases")
    return {
        name: [_unescape(line[1:]) for line in group.split("\n") if line.startswith("K")]
        for name, group in zip(names, groups, strict=True)
    }


def _run_oracle(cases: dict[str, list[str]]) -> dict[str, list[str]]:
    names = list(cases)
    payload = "\n---\n".join("\n".join("K" + _escape(key) for key in cases[name]) for name in names)
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["javac", "-d", work, str(ORACLE)],
            check=True,
            capture_output=True,
        )
        result = subprocess.run(
            ["java", "-cp", work, "DumpHashOrder"],
            input=payload,
            check=True,
            capture_output=True,
            text=True,
        )
    groups = result.stdout.split("---\n")
    if len(groups) != len(names):
        raise SystemExit(f"oracle returned {len(groups)} groups for {len(names)} cases")
    return {
        name: [_unescape(line[1:]) for line in group.split("\n") if line.startswith("K")]
        for name, group in zip(names, groups, strict=True)
    }


def _escape(value: str) -> str:
    out = []
    for unit in value.encode("utf-16-le").decode("utf-16-le"):
        for half in _units(unit):
            if half == 0x5C:
                out.append("\\\\")
            elif 0x20 <= half <= 0x7E:
                out.append(chr(half))
            else:
                out.append(f"\\u{half:04x}")
    return "".join(out)


def _units(character: str) -> tuple[int, ...]:
    code = ord(character)
    if code > 0xFFFF:
        offset = code - 0x10000
        return (0xD800 + (offset >> 10), 0xDC00 + (offset & 0x3FF))
    return (code,)


def _unescape(value: str) -> str:
    units: list[int] = []
    index = 0
    while index < len(value):
        if value.startswith("\\u", index):
            units.append(int(value[index + 2 : index + 6], 16))
            index += 6
        elif value.startswith("\\\\", index):
            units.append(0x5C)
            index += 2
        else:
            units.append(ord(value[index]))
            index += 1
    return b"".join(unit.to_bytes(2, "little") for unit in units).decode("utf-16-le")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    # `gettempdir()` is the per-user directory on macOS, which is not where the jar is kept.
    parser.add_argument("--jar", default=os.environ.get("GTFS_JAR", "/tmp/gtfs-validator.jar"))  # noqa: S108
    arguments = parser.parse_args()

    cases = string_corpora()
    # Both collections, because picking the wrong one is the defect this second pass exists to
    # catch: a plain HashMap starts at 16 buckets and a pre-sized Guava multimap at 32.
    expected = {
        "hashmap": _run_oracle(cases),
        "multimap": _run_multimap_oracle(cases, arguments.jar),
    }
    ours_by_kind = {"hashmap": hashmap_order, "multimap": multimap_order}
    failures = []
    for kind, order in ours_by_kind.items():
        failures.extend(_compare(cases, expected[kind], order, kind, arguments.verbose))

    long_cases = long_corpora()
    failures.extend(
        _compare(
            long_cases,
            _run_long_oracle(long_cases, arguments.jar),
            long_multimap_order,
            "long-multimap",
            arguments.verbose,
        )
    )
    _report(failures)
    total = 2 * len(cases) + len(long_cases)
    print(f"\n{total - len(failures)}/{total} orders match the pinned jar")
    return 1 if failures else 0


def _compare(cases, expected, order, kind, verbose):
    failures = []
    for name, keys in cases.items():
        ours = order(keys)
        theirs = expected[name]
        if ours == theirs:
            if verbose:
                print(f"ok   {kind} {name} ({len(keys)} keys)")
            continue
        first = next(
            (
                index
                for index, pair in enumerate(zip(ours, theirs, strict=False))
                if pair[0] != pair[1]
            ),
            min(len(ours), len(theirs)),
        )
        failures.append(
            (kind, name, len(keys), first, ours[first : first + 4], theirs[first : first + 4])
        )
    return failures


def _report(failures) -> None:
    for kind, name, size, index, ours, theirs in failures:
        print(f"FAIL {kind} {name} ({size} keys): first difference at {index}")
        print(f"       ours: {ours}")
        print(f"       jar:  {theirs}")


if __name__ == "__main__":
    raise SystemExit(main())
