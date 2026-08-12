#!/usr/bin/env python3
"""Build a minimal GTFS feed zip for manual runs and the differential check.

Usage:
    python tools/make_fixture_feed.py tests/fixtures/minimal.zip
    python tools/make_fixture_feed.py --mixed-case tests/fixtures/mixed_case.zip
    python tools/make_fixture_feed.py --wrapped tests/fixtures/wrapped.zip
    python tools/make_fixture_feed.py --clean tests/fixtures/clean.zip

The feed is deliberately imperfect: it carries every required table so the walk
gets past stage 1, omits feed_info.txt, and includes a non-table entry, so a run
against it exercises missing_recommended_file and unknown_file.

The three variants exist because the plain feed cannot show what they show, and
each one stands for a defect the differential job was blind to:

--mixed-case writes the same feed with two tables recased and one entry name
repeated. Upstream matches an entry to a table with `filename.toLowerCase()` and
collects entry names into a set, so the jar's report for it is the plain feed's
report; ours was three notices different until the fold was implemented.

--wrapped writes it inside a folder named after the archive, as Finder does, with
a .DS_Store beside the tables. Upstream takes that folder out of its listing but
not out of its reads, so the jar reports a parse failure per table; ours reported
every table missing instead.

--clean writes a different, conformant feed that the jar reports *nothing* about,
which is the only way to exercise the page's empty notice table. It carries two
GTFS features as well, where the plain feed has none.

They are separate fixtures rather than edits to minimal.zip because the
differential job wants all four, and the plain one is what the other harnesses
read.

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


# A feed the jar reports *nothing* about, which is the only way to see what the
# page looks like with an empty notice table. It also carries two GTFS features,
# where minimal.zip has none, so the repeated-span rendering is exercised too. The
# calendar sits either side of the differential job's DATE so no date rule fires.
CLEAN = {
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone,agency_lang\n"
    "1,Acme Transit,https://example.com,America/New_York,en\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n"
    "S1,Main St,40.7,-74.0\nS2,Second St,40.71,-74.01\n",
    "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n"
    "R1,1,10,Main Line,3\n",
    "trips.txt": "route_id,service_id,trip_id,trip_headsign\nR1,WEEK,T1,Downtown\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
    "T1,08:00:00,08:00:00,S1,1\nT1,08:10:00,08:10:00,S2,2\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,"
    "saturday,sunday,start_date,end_date\nWEEK,1,1,1,1,1,0,0,20260401,20260801\n",
    "feed_info.txt": "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,"
    "feed_end_date,feed_version,feed_contact_email\n"
    "Acme,https://example.com,en,20260401,20260801,1.0,ops@example.com\n",
}


def build(path: Path, variant: str = "plain") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        if variant == "clean":
            for name, body in CLEAN.items():
                zf.writestr(name, body)
            return
        # The wrapper folder Finder puts in a zip, named after the archive so that
        # upstream unwraps it, plus the .DS_Store it drops in beside the tables.
        # The jar lists the unwrapped names and then fails to read any of them.
        prefix = f"{path.name.replace('.zip', '')}/" if variant == "wrapped" else ""
        if prefix:
            zf.writestr(prefix, b"")
        for name, body in TABLES.items():
            zf.writestr(
                prefix + (RECASED.get(name, name) if variant == "mixed-case" else name), body
            )
        if prefix:
            zf.writestr(f"{prefix}.DS_Store", "junk")
        if variant == "mixed-case":
            # A repeated entry name. `getFilenames()` is an ImmutableSet, so the jar
            # sees one routes.txt and reports nothing about the second copy; we
            # loaded it twice. zipfile warns about writing it, which is the point.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                zf.writestr("routes.txt", TABLES["routes.txt"])


VARIANTS = ("mixed-case", "wrapped", "clean")


def main() -> None:
    flags = [arg for arg in sys.argv[1:] if arg.startswith("--")]
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    variants = [flag.removeprefix("--") for flag in flags]
    unknown = [name for name in variants if name not in VARIANTS]
    if unknown or len(variants) > 1:
        raise SystemExit(f"usage: make_fixture_feed.py [--{'|--'.join(VARIANTS)}] TARGET.zip")
    target = Path(args[0] if args else "tests/fixtures/minimal.zip")
    build(target, variant=variants[0] if variants else "plain")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
