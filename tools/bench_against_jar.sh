#!/usr/bin/env bash
# Time the jar and gtfs-validator on the same feeds and diff the reports.
# Usage: bench_against_jar.sh OUT.txt FEED.zip [FEED.zip ...]
# Env: JAR (default /tmp/gtfs-validator.jar), DATE (default 2026-07-27),
#      OURS_TIMEOUT seconds (default 3600).
#
# One line per feed: <name> jar=<s> ours=<s> verdict=<MATCH|DIVERGE|TIMEOUT>.
# The verdict comes from diff_against_upstream.sh, so a fast wrong answer still
# reads DIVERGE: this harness exists to prove speed *and* parity at once, and a
# timing table with no verdict column is how a regression would hide in it.
set -uo pipefail
OUT="$1"; shift
JAR="${JAR:-/tmp/gtfs-validator.jar}"
DATE="${DATE:-2026-07-27}"
OURS_TIMEOUT="${OURS_TIMEOUT:-3600}"
PYTHON="${PYTHON:-.venv/bin/python}"
: > "$OUT"
for feed in "$@"; do
  name="$(basename "$feed" .zip)"
  work="$(mktemp -d /tmp/bench-XXXXXX)"
  start=$(date +%s)
  java -jar "$JAR" -i "$feed" -o "$work/theirs" -d "$DATE" >/dev/null 2>&1
  jar_s=$(( $(date +%s) - start ))
  start=$(date +%s)
  if ! timeout "$OURS_TIMEOUT" env PYTHONPATH=src "$PYTHON" -m gtfs_validator.cli \
      -i "$feed" -o "$work/ours" -d "$DATE" >/dev/null 2>&1; then
    echo "$name jar=${jar_s}s ours=TIMEOUT verdict=TIMEOUT" >> "$OUT"
    rm -rf "$work"; continue
  fi
  ours_s=$(( $(date +%s) - start ))
  verdict="$(DATE="$DATE" PYTHON="$PYTHON" tools/diff_against_upstream.sh "$feed" "$JAR" 2>/dev/null | tail -1)"
  case "$verdict" in
    "MATCH on implemented codes") verdict=MATCH ;;
    *) verdict=DIVERGE ;;
  esac
  echo "$name jar=${jar_s}s ours=${ours_s}s verdict=$verdict" >> "$OUT"
  rm -rf "$work"
done
