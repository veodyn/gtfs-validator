#!/usr/bin/env python3
"""Run the validator over one real feed under time and memory ceilings.

Usage:
    PYTHONPATH=src .venv/bin/python tools/measure_real_scale.py <feed.zip>
    PYTHONPATH=src .venv/bin/python tools/measure_real_scale.py <feed.zip> --seconds 900 --megabytes 4000

**Why this is separate from `measure_scale.py`.** That harness is a routine guard: it builds a
synthetic feed, runs in about half a minute, and is meant to be run on every change. The real tail is
nowhere near it. The largest feed in the corpus carries 12,998,831 `stop_times` rows in a 2 GB
uncompressed file, which is 125 times the synthetic feed and around the ten-million-row figure the
design spec names as its case. Growing the synthetic feed to match would turn the routine guard into
an hour, and a guard nobody runs guards nothing.

So the split is deliberate: `measure_scale.py` stays fast and covers the middle of the real
distribution, and this covers the tail occasionally, on a feed the corpus already holds.

Unlike `measure_scale.py` this asserts nothing about *notices*: a real feed's report is whatever the
feed deserves, and the differential harness is what checks it. What this measures is that the run
finishes, inside a wall clock and a heap.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import tracemalloc
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gtfs_validator.cli import main


def _shape(feed: Path) -> str:
    """The feed's own size, so the printed numbers say what they were measured on."""
    with zipfile.ZipFile(feed) as archive:
        sizes = {info.filename: info.file_size for info in archive.infolist()}
        key = next((n for n in sizes if n.lower().endswith("stop_times.txt")), None)
        rows = 0
        if key is not None:
            with archive.open(key) as handle:
                while chunk := handle.read(1 << 20):
                    rows += chunk.count(b"\n")
    total = sum(sizes.values())
    return (
        f"{feed.name}: {feed.stat().st_size / 1e6:.1f} MB compressed, "
        f"{total / 1e6:.0f} MB expanded, {rows:,} stop_times rows"
    )


def run(feed: Path, seconds: float, megabytes: float, traced: bool) -> int:
    work = Path(tempfile.mkdtemp(prefix="gtfs-validator-real-scale-"))
    try:
        print(_shape(feed))
        if traced:
            tracemalloc.start()
        started = time.perf_counter()
        status = main(["-i", str(feed), "-o", str(work / "out"), "-d", "2026-07-27"])
        elapsed = time.perf_counter() - started
        peak_mb = None
        if traced:
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_mb = peak / 1e6

        print(f"elapsed: {elapsed:.1f}s (ceiling {seconds:.0f}s)")
        if peak_mb is not None:
            print(f"peak Python heap: {peak_mb:.0f} MB (ceiling {megabytes:.0f} MB)")
        else:
            print("peak Python heap: not measured (--traced off, since tracemalloc costs ~2.6x)")

        failures = []
        # The exit status matters most here. A real feed is where a loader raises on input no probe
        # thought of, and a run that dies fast would otherwise read as a fast run.
        if status != 0:
            errors_path = work / "out" / "system_errors.json"
            named = "no system_errors.json written"
            if errors_path.exists():
                errors = json.loads(errors_path.read_text())["notices"]
                named = ", ".join(n["code"] for n in errors) or "no system errors recorded"
            failures.append(f"exited {status} ({named})")
        if elapsed > seconds:
            failures.append(f"took {elapsed:.1f}s, over the {seconds:.0f}s ceiling")
        if peak_mb is not None and peak_mb > megabytes:
            failures.append(f"peaked at {peak_mb:.0f} MB, over the {megabytes:.0f} MB ceiling")
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        if failures:
            return 1
        print("within ceilings")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("--seconds", type=float, default=1800.0)
    parser.add_argument("--megabytes", type=float, default=4000.0)
    parser.add_argument(
        "--traced",
        action="store_true",
        help="measure the peak heap too, which costs about 2.6x on the clock",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(run(args.feed, args.seconds, args.megabytes, args.traced))
