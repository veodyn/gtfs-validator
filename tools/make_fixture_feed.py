#!/usr/bin/env python3
"""Build a minimal GTFS feed zip for manual runs and the differential check.

Usage:
    python tools/make_fixture_feed.py tests/fixtures/minimal.zip

The feed is deliberately imperfect: it carries every required table so the walk
gets past stage 1, omits feed_info.txt, and includes a non-table entry, so a run
against it exercises missing_recommended_file and unknown_file.

The zip is generated rather than checked in because zipfile stamps entries with
the current time, so a committed archive would churn on every regeneration.
"""

from __future__ import annotations

import sys
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


def build(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in TABLES.items():
            zf.writestr(name, body)


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/minimal.zip")
    build(target)
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
