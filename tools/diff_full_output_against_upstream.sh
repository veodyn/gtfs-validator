#!/usr/bin/env bash
# Compare everything diff_against_upstream.sh does not: the report's `summary`
# object and the whole of report.html, byte for byte.
#
# Usage: tools/diff_full_output_against_upstream.sh FEED.zip [JAR]
#   DATE=2026-06-01 PYTHON=.venv/bin/python \
#     tools/diff_full_output_against_upstream.sh tests/fixtures/minimal.zip /tmp/gtfs-validator.jar
#
# The existing harness extracts report["notices"] and compares nothing else,
# which is exactly why the summary block and the HTML report were missing for so
# long without a single red run. This one covers the rest.
#
# Six fields are normalised away and no more: four that differ between any two
# runs (validatedAt, validationTimeSeconds, memoryUsageRecords, outputDirectory)
# and two that differ from the jar on purpose (validatorVersion, gtfsInput). The
# list lives in gtfs_validator.summary, not here, so it cannot be widened locally to
# make a run pass. Widening it is a spec change.
set -euo pipefail

FEED="${1:?usage: diff_full_output_against_upstream.sh FEED.zip [JAR]}"
JAR="${2:-/tmp/gtfs-validator.jar}"
PYTHON="${PYTHON:-python3}"
DATE="${DATE:-}"
DATE_ARGS=()
if [ -n "$DATE" ]; then
  DATE_ARGS=(-d "$DATE")
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PYTHONPATH="${PYTHONPATH:-src}" "$PYTHON" -m gtfs_validator.cli \
  -i "$FEED" -o "$WORK/ours" "${DATE_ARGS[@]}" || true
java -jar "$JAR" -i "$FEED" -o "$WORK/theirs" "${DATE_ARGS[@]}" >/dev/null 2>&1 || true

for side in ours theirs; do
  for name in report.json report.html; do
    if [ ! -f "$WORK/$side/$name" ]; then
      echo "no $name from $side; the run failed rather than diverged" >&2
      exit 1
    fi
  done
done

PYTHONPATH="${PYTHONPATH:-src}" "$PYTHON" - "$WORK" <<'PY'
import json
import sys
from pathlib import Path

from gtfs_validator.summary import IMPLEMENTATION_DEPENDENT, RUN_DEPENDENT

work = Path(sys.argv[1])
drop = set(RUN_DEPENDENT) | set(IMPLEMENTATION_DEPENDENT)
failed = False


def summary(side):
    report = json.loads((work / side / "report.json").read_text(encoding="utf-8"))
    return {k: v for k, v in (report.get("summary") or {}).items() if k not in drop}


ours, theirs = summary("ours"), summary("theirs")
if list(ours) != list(theirs):
    failed = True
    print("summary key order differs")
    print(f"  ours  : {list(ours)}")
    print(f"  theirs: {list(theirs)}")
for key in theirs:
    if ours.get(key) != theirs[key]:
        failed = True
        print(f"summary.{key}")
        print(f"  ours  : {json.dumps(ours.get(key), ensure_ascii=False)[:400]}")
        print(f"  theirs: {json.dumps(theirs[key], ensure_ascii=False)[:400]}")
for key in ours:
    if key not in theirs:
        failed = True
        print(f"summary.{key} present here and absent upstream")

# The HTML carries the same six values inline, so the same normalisation has to
# reach it. Substituting the jar's values into our page is the only way to
# compare the remaining bytes; anything still different after that is real.
def html(side):
    return (work / side / "report.html").read_text(encoding="utf-8")


mine, yours = html("ours"), html("theirs")
ours_full = json.loads((work / "ours" / "report.json").read_text(encoding="utf-8"))["summary"]
theirs_full = json.loads((work / "theirs" / "report.json").read_text(encoding="utf-8"))["summary"]
for key in ("validatorVersion", "validatedAt", "gtfsInput"):
    mine_value, their_value = ours_full.get(key), theirs_full.get(key)
    if mine_value and their_value:
        mine = mine.replace(str(mine_value), str(their_value))

if mine != yours:
    failed = True
    mine_lines, your_lines = mine.split("\n"), yours.split("\n")
    print(f"report.html differs: {len(mine)} bytes here, {len(yours)} upstream")
    shown = 0
    for index in range(max(len(mine_lines), len(your_lines))):
        left = mine_lines[index] if index < len(mine_lines) else "<absent>"
        right = your_lines[index] if index < len(your_lines) else "<absent>"
        if left != right:
            print(f"  line {index + 1}")
            print(f"    ours  : {left!r}")
            print(f"    theirs: {right!r}")
            shown += 1
            if shown == 10:
                print("  ... further differences suppressed")
                break

if failed:
    sys.exit(1)
print("MATCH on summary and report.html")
PY
