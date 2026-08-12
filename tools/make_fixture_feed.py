#!/usr/bin/env python3
"""Build a minimal GTFS feed zip for manual runs and the differential check.

Usage:
    python tools/make_fixture_feed.py tests/fixtures/minimal.zip
    python tools/make_fixture_feed.py --mixed-case tests/fixtures/mixed_case.zip

The feed is deliberately imperfect: it carries every required table so the walk
gets past stage 1, omits feed_info.txt, and includes a non-table entry, so a run
against it exercises missing_recommended_file and unknown_file.

--mixed-case writes the same feed with two tables recased and one entry name
repeated. Upstream matches an entry to a table with `filename.toLowerCase()` and
collects entry names into a set, so the jar's report for it is the plain feed's
report; ours was three notices different until the fold was implemented. It is a
separate fixture rather than a recased minimal.zip because the differential job
wants both, and the plain one is what the other harnesses read.

The zip is generated rather than checked in because zipfile stamps entries with
the current time, so a committed archive would churn on every regeneration.
"""

from __future__ import annotations

import sys
import warnings
import zipfile
from pathlib import Path

TABLES = {
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n"
    "1,Acme Transit,https://example.com,America/New_York\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nS1,Main St,40.7,-74.0\n",
    "routes.txt": "route_id,agency_id,route_short_name,route_type\nR1,1,10,3\n",
    "trips.txt": "route_id,service_id,trip_id\nR1,WEEK,T1\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
    "T1,08:00:00,08:00:00,S1,1\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,"
    "saturday,sunday,start_date,end_date\nWEEK,1,1,1,1,1,0,0,20260101,20261231\n",
    "notes.md": "Not a GTFS table. Present so unknown_file fires.\n",
}


# agency.txt is @Required and stops.txt is @ConditionallyRequired through a rule
# validator, so between them they cover both paths that report a table as missing.
# The extension is recased too: the match folds the whole name, not the stem.
RECASED = {"agency.txt": "Agency.txt", "stops.txt": "Stops.TXT"}


def build(path: Path, mixed_case: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in TABLES.items():
            zf.writestr(RECASED.get(name, name) if mixed_case else name, body)
        if mixed_case:
            # A repeated entry name. `getFilenames()` is an ImmutableSet, so the jar
            # sees one routes.txt and reports nothing about the second copy; we
            # loaded it twice. zipfile warns about writing it, which is the point.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                zf.writestr("routes.txt", TABLES["routes.txt"])


def main() -> None:
    args = [arg for arg in sys.argv[1:] if arg != "--mixed-case"]
    mixed_case = "--mixed-case" in sys.argv[1:]
    target = Path(args[0] if args else "tests/fixtures/minimal.zip")
    build(target, mixed_case=mixed_case)
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
