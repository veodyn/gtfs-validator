#!/usr/bin/env python3
"""Run the validator over a large synthetic feed under time and memory ceilings.

The differential harness cannot see this class of defect at all. Every probe feed
is a few rows spanning a few months, so a rule that is quadratic in the number of
calendar runs, or that materialises a table the store holds on disk, produces
identical notices and a green diff. Nine of plan 5's sixteen review findings were
of exactly that kind, and each was found by reading code rather than by running
anything.

This closes the gap the same way `diff_against_upstream.sh` closes the parity one:
by making the property observable and failing loudly when it regresses.

Usage:
    PYTHONPATH=src .venv/bin/python tools/measure_scale.py
    PYTHONPATH=src .venv/bin/python tools/measure_scale.py --seconds 30 --megabytes 400

The ceilings are deliberately generous. The point is to catch a change that makes
validation impossible on a real feed, not to police a few percent: a tighter
budget on shared CI hardware would fail for reasons that have nothing to do with
the code.

**What this feed does not cover.** It is an ordinary scheduled feed, so nothing
here exercises the flex rules: there is no `locations.geojson` and no stop time
naming a `location_id`, which leaves `overlapping_zone_and_pickup_drop_off_window`
doing nothing at all, despite being quadratic in a trip's stop times and calling an
exact-arithmetic polygon predicate on each pair. A flex version of this feed would
change what every other rule sees, so the gap is recorded rather than papered over:
"within ceilings" means the scheduled path, and a change to the zone rule's cost is
not measured by anything.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _scale_canaries import (
    foreign_key_canary,
    headsign_canary,
    reachability_canary,
    shape_matching_canary,
    unmeasured_scans,
)
from _scale_feed import (
    EXCEPTIONS,
    LONG_TRIP_STOPS,
    LONG_TRIPS,
    SERVICES,
    TRIPS_PER_SERVICE,
    build_feed,
)

from gtfs_validator.cli import main


def run(seconds: float, megabytes: float) -> int:
    work = Path(tempfile.mkdtemp(prefix="gtfs-validator-scale-"))
    try:
        feed = work / "big.zip"
        build_feed(feed)
        size_mb = feed.stat().st_size / 1e6
        print(f"feed: {size_mb:.1f} MB compressed, {SERVICES} services, ", end="")
        print(
            f"{SERVICES * TRIPS_PER_SERVICE} trips plus {LONG_TRIPS} of "
            f"{LONG_TRIP_STOPS} stop times, {EXCEPTIONS} calendar_dates rows"
        )

        # Two runs, because `tracemalloc` hooks every allocation and costs about 2.6x on this
        # feed. Measuring both at once meant the elapsed time was mostly the profiler, so the
        # ceiling policed the instrument rather than the validator, and the reading moved with
        # how many allocations a change made rather than how much work it did.
        started = time.perf_counter()
        # main reports a runtime failure through its exit status rather than by
        # raising. Discarding it let a run that died early finish fast, inside both
        # ceilings, and print "within ceilings": the harness would have certified
        # exactly the regression it exists to catch.
        exit_status = main(["-i", str(feed), "-o", str(work / "out"), "-d", "2026-06-01"])
        elapsed = time.perf_counter() - started

        tracemalloc.start()
        traced_status = main(["-i", str(feed), "-o", str(work / "traced"), "-d", "2026-06-01"])
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mb = peak / 1e6

        print(f"elapsed: {elapsed:.1f}s (ceiling {seconds:.0f}s, untraced run)")
        print(f"peak Python heap: {peak_mb:.0f} MB (ceiling {megabytes:.0f} MB, traced run)")
        failures = []
        # Both runs, since a failure that only the traced one hits is still a failure, and
        # skipping its status would be the same hole discarding the first one used to be.
        for label, status in (("timed", exit_status), ("traced", traced_status)):
            if status == 0:
                continue
            directory = "out" if label == "timed" else "traced"
            errors = json.loads((work / directory / "system_errors.json").read_text())["notices"]
            named = ", ".join(notice["code"] for notice in errors) or "no system errors recorded"
            failures.append(f"the {label} run exited {status} ({named})")
        if elapsed > seconds:
            failures.append(f"took {elapsed:.1f}s, over the {seconds:.0f}s ceiling")
        if peak_mb > megabytes:
            failures.append(f"peaked at {peak_mb:.0f} MB, over the {megabytes:.0f} MB ceiling")
        report = work / "out" / "report.json"
        for canary in (
            unmeasured_scans,
            headsign_canary,
            shape_matching_canary,
            reachability_canary,
            foreign_key_canary,
        ):
            failures.extend(canary(report))
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
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--megabytes", type=float, default=600.0)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(run(args.seconds, args.megabytes))
