#!/usr/bin/env bash
# Run one feed at -t 1 and -t N and compare both report files.
# Usage: diff_across_threads.sh FEED.zip [N]
# Env: PYTHON (default .venv/bin/python), DATE (default 2026-07-27).
#
# The parallel stages are only correct if this passes: the merge order is the
# feature, and "same notices, different order" is a defect here even though the
# differential comparator would forgive it.
#
# system_errors.json is still compared byte for byte. report.json no longer can
# be, because its `summary` carries a wall clock, an elapsed time and a memory
# reading, so two runs of the same feed differ whatever the thread count. Those
# four fields come from gtfs_validator.summary.RUN_DEPENDENT rather than a list kept
# here, plus `threads`, which legitimately differs because varying it is the
# whole point of this script. Everything else, including every other summary
# field and the entire notices array, is still held to exact equality.
set -uo pipefail
FEED="$1"
N="${2:-4}"
PYTHON="${PYTHON:-.venv/bin/python}"
DATE="${DATE:-2026-07-27}"
WORK="$(mktemp -d /tmp/threads-diff-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
PYTHONPATH=src "$PYTHON" -m gtfs_validator.cli -i "$FEED" -o "$WORK/one" -d "$DATE" -t 1 >/dev/null || exit 1
PYTHONPATH=src "$PYTHON" -m gtfs_validator.cli -i "$FEED" -o "$WORK/many" -d "$DATE" -t "$N" >/dev/null || exit 1

if ! cmp -s "$WORK/one/system_errors.json" "$WORK/many/system_errors.json"; then
  echo "DIFFERS: system_errors.json between -t 1 and -t $N on $(basename "$FEED")"
  exit 1
fi

PYTHONPATH=src "$PYTHON" - "$WORK" "$N" "$(basename "$FEED")" <<'PY' || exit 1
import json
import sys

from gtfs_validator.summary import normalise

work, threads, name = sys.argv[1], sys.argv[2], sys.argv[3]


def report(side):
    with open(f"{work}/{side}/report.json", encoding="utf-8") as handle:
        payload = normalise(json.load(handle))
    payload["summary"].pop("threads", None)
    return payload


one, many = report("one"), report("many")
if one == many:
    sys.exit(0)

print(f"DIFFERS: report.json between -t 1 and -t {threads} on {name}")
if one["notices"] != many["notices"]:
    print("  the notices array differs, which is the merge order defect this exists to catch")
for key in sorted(set(one["summary"]) | set(many["summary"])):
    if one["summary"].get(key) != many["summary"].get(key):
        print(f"  summary.{key}: {one['summary'].get(key)!r} vs {many['summary'].get(key)!r}")
sys.exit(1)
PY

echo "IDENTICAL at -t 1 and -t $N: $(basename "$FEED")"
