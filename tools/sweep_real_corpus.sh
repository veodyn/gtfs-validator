#!/usr/bin/env bash
# Sweep every feed in a cache directory against the jar, keeping each feed's
# full diff output for triage. One verdict line per feed, smallest feed first
# so cheap findings surface before the giants finish.
#
# Usage: tools/sweep_real_corpus.sh OUTDIR CACHE_DIR [JAR]
#   DATE=2026-07-27 THREADS=6 tools/sweep_real_corpus.sh /tmp/sweep ~/feeds
#
# THREADS and DATE pass through to diff_against_upstream.sh. The verdict is the
# harness's own exit status; nothing here relaxes the comparison.
set -uo pipefail
OUT="${1:?usage: sweep_real_corpus.sh OUTDIR CACHE_DIR [JAR]}"
CACHE="${2:?usage: sweep_real_corpus.sh OUTDIR CACHE_DIR [JAR]}"
JAR="${3:-/tmp/gtfs-validator.jar}"
cd "$(dirname "$0")/.."
mkdir -p "$OUT"
: > "$OUT/verdicts.txt"
while IFS= read -r feed; do
  name="$(basename "$feed" .zip)"
  start=$(date +%s)
  if PYTHONPATH=src PYTHON="${PYTHON:-.venv/bin/python}" \
      tools/diff_against_upstream.sh "$feed" "$JAR" \
      > "$OUT/$name.diff.txt" 2>&1; then
    verdict=MATCH
  else
    verdict=DIVERGE
  fi
  echo "$verdict $name $(( $(date +%s) - start ))s" >> "$OUT/verdicts.txt"
done < <(ls -Sr "$CACHE"/*.zip)
echo "done $(wc -l < "$OUT/verdicts.txt") feeds" >> "$OUT/verdicts.txt"
