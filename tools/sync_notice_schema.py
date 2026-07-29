#!/usr/bin/env python3
"""Regenerate notice_schema.json by running the pinned jar's own exporter.

Upstream ships a generator for this file (`NoticeSchemaGenerator`, reachable as
`--export_notices_schema`), so we run it rather than transcribe its inputs. The
alternative was teaching `sync_upstream_notices.py` to parse Javadoc, because
`shortSummary` and each field's `description` live in comments that its regexes
cannot see. Same lesson as the JTS and phone-number tables: an oracle beats a
transcription, and here the oracle is upstream's own code path.

The bytes are stored exactly as the jar emits them (compact, keys sorted, no
trailing newline) because `gtfs-validator -n` has to reproduce them. Anything this
script reformatted would be a difference our own `-n` parity check then reports.

Usage:
    tools/sync_notice_schema.py --jar /private/tmp/gtfs-validator.jar

Writes src/gtfs_validator/data/notice_schema.json. Needs a JDK, at generation time only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "src" / "gtfs_validator" / "data" / "notice_schema.json"
CANONICAL = ROOT / "src" / "gtfs_validator" / "data" / "canonical_notices.json"

# The jar's export covers validation notices and system errors alike. These five
# are the system errors: they are absent from canonical_notices.json, which is
# scoped to codes a feed can provoke, and present here because upstream's
# generator walks every Notice subclass.
SYSTEM_ERROR_CODES = frozenset(
    {
        "i_o_error",
        "runtime_exception_in_loader_error",
        "runtime_exception_in_validator_error",
        "thread_execution_error",
        "u_r_i_syntax_error",
    }
)

ENTRY_REQUIRED_KEYS = frozenset({"code", "severityLevel", "type", "properties", "deprecated"})


def export(jar: Path) -> str:
    """Run the jar's schema exporter and return the file's exact text."""
    with tempfile.TemporaryDirectory() as work:
        subprocess.run(
            ["java", "-jar", str(jar), "-n", "-o", work],
            capture_output=True,
            text=True,
            check=True,
        )
        written = Path(work) / "notice_schema.json"
        if not written.is_file():
            raise SystemExit(f"the jar wrote no notice_schema.json into {work}")
        return written.read_text(encoding="utf-8")


def check(text: str) -> dict[str, dict]:
    """Reject an export that does not have the shape the rest of the tree assumes.

    Cheap assertions, but each one has a failure it prevents: a jar that is not
    the pinned one, a Gson change that renames a key, or a run that produced a
    truncated file because the JVM died mid-write.
    """
    schema = json.loads(text)
    if not isinstance(schema, dict) or not schema:
        raise SystemExit("export is not a non-empty JSON object")

    for code, entry in schema.items():
        missing = ENTRY_REQUIRED_KEYS - set(entry)
        if missing:
            raise SystemExit(f"{code}: export is missing {sorted(missing)}")
        if entry["code"] != code:
            raise SystemExit(f"{code}: entry disagrees with its own key ({entry['code']})")

    canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))["notices"]
    expected = set(canonical) | SYSTEM_ERROR_CODES
    if set(schema) != expected:
        extra = sorted(set(schema) - expected)
        absent = sorted(expected - set(schema))
        raise SystemExit(f"code set disagrees with canonical_notices.json: {extra=} {absent=}")

    for code, entry in canonical.items():
        if schema[code]["severityLevel"] != entry["severity"]:
            raise SystemExit(
                f"{code}: severity {schema[code]['severityLevel']} in the export, "
                f"{entry['severity']} in canonical_notices.json"
            )
    return schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path, help="the pinned upstream CLI jar")
    args = parser.parse_args()

    if not args.jar.is_file():
        raise SystemExit(f"no jar at {args.jar}")

    text = export(args.jar)
    schema = check(text)
    OUTPUT.write_text(text, encoding="utf-8")

    deprecated = sorted(code for code, entry in schema.items() if entry["deprecated"])
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(schema)} entries, {len(text)} bytes")
    print(f"  system errors: {len(SYSTEM_ERROR_CODES)}")
    print(f"  deprecated:    {', '.join(deprecated)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
