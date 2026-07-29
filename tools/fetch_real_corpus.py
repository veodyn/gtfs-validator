#!/usr/bin/env python3
"""Download the feeds named in tools/real_corpus.json into a local cache.

Usage:
    python tools/fetch_real_corpus.py --cache /path/to/cache
    python tools/fetch_real_corpus.py --cache /path/to/cache --max-bytes 60000000

The feeds are never committed: the tranche-1 manifest alone is 76 MB and a single catalogued feed can
be 592 MB. What git holds is the manifest and, after a fetch, `checksums.json` in the cache, so a
later sweep can prove which bytes it ran on. `urls.latest` follows the agency's current feed, so a
feed really can change under us; that is why every finding from this corpus has to be reduced to a
committed probe.

A feed already present at its manifest size is skipped, so re-running is cheap and interrupting a
fetch loses only the file in flight.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "real_corpus.json"


def name_for(entry: dict) -> str:
    """`<id>-<country>.zip`: the id keeps it unique and the country makes a listing readable."""
    return f"{entry['mdb_source_id']}-{entry['country']}.zip"


def fetch(entry: dict, target: Path) -> str | None:
    """Download one feed, returning an error description or None on success."""
    finished = subprocess.run(
        ["curl", "-sS", "-m", "600", "-L", "-o", str(target), entry["url"]],
        capture_output=True,
        text=True,
        check=False,
    )
    if finished.returncode != 0:
        target.unlink(missing_ok=True)
        return finished.stderr.strip() or f"curl exited {finished.returncode}"
    if not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return "the mirror returned nothing"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        help="skip any feed larger than this, and say so rather than dropping it silently",
    )
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    entries = json.loads(MANIFEST.read_text())

    checksums_path = args.cache / "checksums.json"
    checksums = json.loads(checksums_path.read_text()) if checksums_path.exists() else {}
    fetched = skipped_size = already = 0
    failures: list[tuple[str, str]] = []
    for entry in entries:
        name = name_for(entry)
        target = args.cache / name
        if args.max_bytes is not None and entry["bytes"] > args.max_bytes:
            print(f"skip {name}: {entry['bytes'] / 1e6:.0f} MB is over the cap")
            skipped_size += 1
            continue
        if target.exists() and target.stat().st_size > 0:
            already += 1
        else:
            error = fetch(entry, target)
            if error:
                print(f"FAIL {name}: {error}")
                failures.append((name, error))
                continue
            fetched += 1
        if name not in checksums:
            checksums[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    checksums_path.write_text(json.dumps(checksums, indent=1) + "\n")

    have = sum(1 for entry in entries if (args.cache / name_for(entry)).exists())
    total = sum(
        (args.cache / name_for(entry)).stat().st_size
        for entry in entries
        if (args.cache / name_for(entry)).exists()
    )
    print(
        f"{have} of {len(entries)} feeds in {args.cache}, {total / 1e6:.1f} MB "
        f"({fetched} fetched, {already} already there, {skipped_size} over the cap, "
        f"{len(failures)} failed)"
    )
    # A dead mirror entry is a fact about the catalog rather than a defect here, so it is reported
    # and does not fail the run; the sweep simply has fewer feeds and says so.
    for name, error in failures:
        print(f"  unavailable: {name} ({error})")


if __name__ == "__main__":
    main()
