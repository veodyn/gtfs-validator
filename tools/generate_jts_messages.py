#!/usr/bin/env python3
"""Generate the JTS message table invalid_geometry reports, by running the pinned jar.

`GeoJsonGeometryValidator` puts one of two strings in the notice's `message`:

- `new IsValidOp(geometry).getValidationError().getMessage()`, from JTS's fixed
  TopologyValidationError table, when JTS builds the geometry and then rejects it;
- `IllegalArgumentException.getMessage()`, when GeometryFactory refuses to build it.

Both are read out of the jar rather than transcribed, because transcription was measurably
wrong: a plain reading of JTS says a LinearRing needs four points, and the pinned jar
accepts three and says "must be 0 or >= 3". Same lesson as the phone-number tables.

Usage:
    tools/generate_jts_messages.py --jar /private/tmp/gtfs-validator.jar

Writes src/gtfs_validator/data/jts_messages.json. Needs a JDK, at generation time only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JAVA_SOURCE = ROOT / "tools" / "jts" / "DumpMessages.java"
OUTPUT = ROOT / "src" / "gtfs_validator" / "data" / "jts_messages.json"

# TopologyValidationError's codes. The names are ours, for readability at the call site;
# every message string comes from the jar.
ERROR_NAMES = {
    0: "TOPOLOGY_VALIDATION_ERROR",
    1: "REPEATED_POINT",
    2: "HOLE_OUTSIDE_SHELL",
    3: "NESTED_HOLES",
    4: "DISCONNECTED_INTERIOR",
    5: "SELF_INTERSECTION",
    6: "RING_SELF_INTERSECTION",
    7: "NESTED_SHELLS",
    8: "DUPLICATE_RINGS",
    9: "TOO_FEW_POINTS",
    10: "INVALID_COORDINATE",
    11: "RING_NOT_CLOSED",
}


def run_oracle(jar: Path) -> dict[str, dict[str, str]]:
    result = subprocess.run(
        ["java", "-cp", str(jar), str(JAVA_SOURCE)],
        capture_output=True,
        text=True,
        check=True,
    )
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("### "):
            current = {}
            sections[line[4:]] = current
        elif line.strip():
            key, _, value = line.partition("\t")
            current[key] = value
    return sections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=Path("/private/tmp/gtfs-validator.jar"))
    args = parser.parse_args()
    if not args.jar.exists():
        print(f"jar not found: {args.jar}", file=sys.stderr)
        return 1

    sections = run_oracle(args.jar)
    messages = sections["error_messages"]
    by_name = {}
    for code, name in ERROR_NAMES.items():
        message = messages.get(f"code_{code}")
        if message is None or message == "UNAVAILABLE":
            print(f"no message for error code {code}", file=sys.stderr)
            return 1
        by_name[name] = message

    construction = sections["construction_errors"]
    payload = {
        "_meta": {
            "source": "org.locationtech.jts, as bundled in the pinned gtfs-validator jar",
            "generator": "tools/generate_jts_messages.py",
            "note": (
                "Generated. Edit the generator and re-run; a hand edit makes the drift "
                "test lie. ACCEPTED means the pinned JTS builds that ring rather than "
                "refusing it, which is itself part of the contract."
            ),
        },
        "topology_errors": by_name,
        "construction_errors": construction,
        # Kept so a change in which error JTS reports for a known shape shows up as a
        # diff in review rather than silently altering a notice's message.
        "measured_cases": sections["validation_cases"],
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(by_name)} messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
