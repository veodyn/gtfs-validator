#!/usr/bin/env bash
# Compare gtfs-validator against the upstream jar on a single feed, restricted to the
# notice codes this build implements. Requires java and the v8.0.1 jar.
#
# Usage: tools/diff_against_upstream.sh FEED.zip [JAR]
#   PYTHON=.venv/bin/python tools/diff_against_upstream.sh tests/fixtures/minimal.zip /tmp/gtfs-validator.jar
#   DATE=2026-06-01 PYTHON=.venv/bin/python tools/diff_against_upstream.sh feed.zip jar
#
# A red diff is the deliverable, not an obstacle. Never narrow the comparison to
# make it pass; fix the implementation or record the divergence and its cause.
set -euo pipefail

FEED="${1:?usage: diff_against_upstream.sh FEED.zip [JAR]}"
JAR="${2:-gtfs-validator-8.0.1-cli.jar}"
PYTHON="${PYTHON:-python3}"
# The date-dependent rules read "today", so both sides must be told the same one
# or a feed whose calendar expires next week diverges for a reason that is not a
# defect. ISO_LOCAL_DATE, which is what both CLIs take.
DATE="${DATE:-}"
DATE_ARGS=()
if [ -n "$DATE" ]; then
  DATE_ARGS=(-d "$DATE")
fi
# Opt-in only. Safe to use here because tools/diff_across_threads.sh holds the
# parallel path to byte-identical reports; the default stays the sequential run.
THREADS="${THREADS:-1}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Both sides exit nonzero on a feed carrying errors, which is the interesting
# case. Under `set -e` an unguarded call would abort before anything is compared.
"$PYTHON" -m gtfs_validator.cli -i "$FEED" -o "$WORK/ours" "${DATE_ARGS[@]}" -t "$THREADS" || true
java -jar "$JAR" -i "$FEED" -o "$WORK/theirs" "${DATE_ARGS[@]}" >/dev/null || true

for side in ours theirs; do
  if [ ! -f "$WORK/$side/report.json" ]; then
    echo "no report.json from $side; the run failed rather than diverged" >&2
    exit 1
  fi
done

# Filter by set membership against IMPLEMENTED rather than by a built regex:
# notice codes are plain identifiers, and a set lookup cannot mis-anchor.
extract() {
  "$PYTHON" - "$1" <<'PY'
import json
import sys
from pathlib import Path

from gtfs_validator.manifest import IMPLEMENTED

report = json.loads(Path(sys.argv[1]).read_text())
for notice in sorted(report["notices"], key=lambda n: n["code"]):
    if notice["code"] not in IMPLEMENTED:
        continue
    print(notice["code"], notice["severity"], notice["totalNotices"])
    # Parity level C covers each sample's context keys and values, so comparing
    # counts alone leaves every context field unchecked. It did: the four header
    # notices reported a zero-based column index against upstream's one-based one
    # through two plans of green runs.
    #
    # Samples are compared as a sorted multiset rather than a sequence. Emission
    # order across files is not part of the contract and genuinely differs (the
    # jar loads tables in its own order), whereas a missing, extra, or wrong
    # sample still shows up. Sorting on the serialised form keeps that stable
    # without assuming which context keys a code carries.
    for sample in sorted(json.dumps(s, sort_keys=True) for s in notice["sampleNotices"]):
        print(f"    {sample}")
PY
}

# system_errors.json carries only *which* runtime failures happened, so only the
# codes are compared, not their contexts. The messages are Java exception strings on
# one side and Python ones on the other, and several differ deliberately: see
# divergences 3, 5 and 6. Comparing codes still catches the two failure modes that
# have actually happened here, a run that dies where upstream succeeds and a run
# that silently succeeds where upstream reports nothing, and it would have caught
# both defects that hid in this file.
system_codes() {
  "$PYTHON" - "$1" <<'SYSPY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    sys.exit(0)
for notice in sorted(json.loads(path.read_text())["notices"], key=lambda n: n["code"]):
    print(notice["code"], notice["totalNotices"])
SYSPY
}

status=0
if ! diff <(extract "$WORK/ours/report.json") <(extract "$WORK/theirs/report.json"); then
  echo "DIVERGENCE above in report.json: left is ours, right is upstream"
  status=1
fi
# Expected to differ on any feed carrying a recorded divergence, so this reports
# rather than fails: an unexpected line here is the signal, not a red exit.
if ! diff <(system_codes "$WORK/ours/system_errors.json") \
          <(system_codes "$WORK/theirs/system_errors.json") >/dev/null; then
  echo "NOTE: system_errors.json codes differ (left ours, right upstream):"
  diff <(system_codes "$WORK/ours/system_errors.json") \
       <(system_codes "$WORK/theirs/system_errors.json") | sed "s/^/  /" || true
fi
if [ "$status" -eq 0 ]; then
  echo "MATCH on implemented codes"
else
  exit 1
fi
