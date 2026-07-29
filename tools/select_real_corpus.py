#!/usr/bin/env python3
"""Choose a differential corpus of real feeds from the Mobility Database catalog.

Usage:
    python tools/select_real_corpus.py --tranche 1 --catalog /tmp/mdb.csv
    python tools/select_real_corpus.py --tranche 2 --catalog /tmp/mdb.csv

Writes tools/real_corpus.json. Deterministic: candidates are ordered by
(country, mdb_source_id) and taken round-robin across countries, so no seed is involved and a
re-run after a catalog refresh changes the selection only where the catalog changed.

**Why bands rather than a flat count.** Measured on 2026-07-27 over one feed per country: median
1.1 MB, p90 45.8 MB, maximum 592 MB, and the 82 resolved sizes summed to 1.75 GB. A flat "take 50"
would be mostly decided by which countries happen to publish large feeds, and could pull half a
gigabyte without meaning to.

Sizes come from `x-goog-stored-content-length`. The mirror serves gzip, so `content-length` is
absent and a first attempt at this read no sizes at all. They are cached in
`tools/.real_corpus_sizes.json`, because asking 2,200 servers for a header is not something to
repeat casually; delete that file to re-measure.

`urls.latest` is the Mobility Database's own mirror rather than the agency's URL, so this neither
depends on agency uptime nor sends traffic their way.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "real_corpus.json"
SIZES = HERE / ".real_corpus_sizes.json"

# Upper bound of each band in bytes, and the quota per tranche.
BANDS = (
    ("tiny", 100_000),
    ("small", 1_000_000),
    ("medium", 10_000_000),
    ("large", 50_000_000),
    ("huge", None),
)
QUOTAS = {
    1: {"tiny": 15, "small": 15, "medium": 20},
    2: {"tiny": 15, "small": 15, "medium": 20, "large": 8, "huge": 2},
}


def candidates(catalog: Path) -> list[dict]:
    """Open static feeds carrying a mirror url, ordered deterministically."""
    rows = [row for row in csv.DictReader(catalog.open()) if row["data_type"] == "gtfs"]
    # authentication_type 0 and empty both mean no credentials; 1 and 2 need a key we do not have.
    found = [
        row
        for row in rows
        if row["urls.authentication_type"].strip() in ("", "0")
        and row.get("urls.latest", "").strip()
    ]
    return sorted(found, key=lambda row: (row["location.country_code"], int(row["mdb_source_id"])))


def _measure(url: str) -> int | None:
    """The stored byte size from a HEAD request, or None when the mirror will not say."""
    finished = subprocess.run(
        ["curl", "-sSI", "-m", "20", "-L", url], capture_output=True, text=True, check=False
    )
    for line in finished.stdout.splitlines():
        if line.lower().startswith("x-goog-stored-content-length"):
            return int(line.split(":", 1)[1].strip())
    return None


def load_sizes() -> dict[str, int | None]:
    return json.loads(SIZES.read_text()) if SIZES.exists() else {}


def size_of(row: dict, known: dict[str, int | None]) -> int | None:
    """The row's size, measuring and caching it only if it is not already known.

    Measured lazily rather than up front. Filling the quotas needs a few hundred sizes, and asking
    all 2,200 candidates for a header to then use fifty of them is a needless few thousand requests
    against someone else's storage.
    """
    key = row["mdb_source_id"]
    if key not in known:
        known[key] = _measure(row["urls.latest"])
        SIZES.write_text(json.dumps(known))
    return known[key]


def band_of(size: int) -> str:
    for name, limit in BANDS:
        if limit is None or size < limit:
            return name
    return "huge"


def interleaved(rows: list[dict]) -> list[dict]:
    """The candidates reordered one country at a time, so a walk down the list spreads regionally.

    The US alone is 1,157 of the 2,200 candidates, so walking the catalog in its own order would fill
    every band with American feeds before reaching anywhere else.
    """
    by_country: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_country[row["location.country_code"]].append(row)
    order: list[dict] = []
    for depth in range(max(len(group) for group in by_country.values())):
        for country in sorted(by_country):
            if depth < len(by_country[country]):
                order.append(by_country[country][depth])
    return order


def select(catalog: Path, tranche: int) -> list[dict]:
    quotas = dict(QUOTAS[tranche])
    rows = interleaved(candidates(catalog))
    print(f"{len(rows)} candidates; measuring until every band is filled")
    known = load_sizes()
    chosen: list[dict] = []
    counts: dict[str, int] = collections.defaultdict(int)
    unresolved = 0
    for row in rows:
        if all(counts[name] >= wanted for name, wanted in quotas.items()):
            break
        size = size_of(row, known)
        if size is None:
            unresolved += 1
            continue
        # A zero-byte mirror entry is a broken upload, not a feed worth comparing.
        if size == 0:
            continue
        band = band_of(size)
        if band not in quotas or counts[band] >= quotas[band]:
            continue
        counts[band] += 1
        chosen.append(
            {
                "mdb_source_id": int(row["mdb_source_id"]),
                "country": row["location.country_code"],
                "url": row["urls.latest"],
                "bytes": size,
                "band": band,
            }
        )
    print(f"measured {len(known)} sizes, {unresolved} the mirror would not report (skipped)")
    for name, wanted in quotas.items():
        print(f"  {name}: {counts[name]} of {wanted}")
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--tranche", type=int, choices=sorted(QUOTAS), default=1)
    args = parser.parse_args()
    chosen = select(args.catalog, args.tranche)
    OUT.write_text(json.dumps(chosen, indent=1) + "\n")
    total = sum(entry["bytes"] for entry in chosen)
    countries = len({entry["country"] for entry in chosen})
    print(f"wrote {OUT} with {len(chosen)} feeds, {countries} countries, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
