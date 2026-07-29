#!/usr/bin/env python3
"""Regenerate upstream/notice-origins-<tag>.json from a pinned checkout.

Usage:
    python tools/map_notice_origins.py --checkout /path/to/upstream --measured-on 2026-07-24

Maps every upstream class extending ValidationNotice to the file that defines it
and infers which pipeline layer emits it. This is the artifact the design spec
cites when it corrects the engine's share of the notice surface from ~50% to 22%.

Layer inference is mechanical and deliberately conservative. A notice whose class
lives in a shared `notice/` package rather than inside its emitter cannot be
attributed by path alone, so the origin records where it is *constructed*. The 14
that construct from neither engine nor rule code stay `geojson-or-standalone`;
the spec hand-assigns those 14 (8 GeoJSON, 5 rule, 1 parse) and says so. Do not
bake that hand assignment in here, or the artifact stops being a measurement.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "upstream"


def out_path(tag: str) -> Path:
    """The artifact is named after the tag it measured.

    This was hardcoded to v8.0.1 while `--tag` was already an argument, so the
    first pin bump would have written v8.0.2 data into the file named v8.0.1 and
    left no record that the older measurement ever existed.
    """
    return DOCS / f"notice-origins-{tag}.json"


CLASS_RE = re.compile(
    r"(@GtfsValidationNotice\s*\((?:[^()]|\([^()]*\))*\)\s*)?"
    r"(public\s+)?(static\s+)?(final\s+)?class\s+(\w+Notice)\s+extends\s+ValidationNotice",
    re.S,
)
# Must skip the enum qualifier: `severity = SeverityLevel.ERROR` would otherwise
# capture "SeverityLevel". The committed artifact had one such entry corrected by
# hand, which is the drift this generator exists to prevent.
SEVERITY_RE = re.compile(r"severity\s*=\s*(?:SeverityLevel\.)?(ERROR|WARNING|INFO)")
CONSTRUCT_RE = re.compile(r"new (\w+Notice)\s*\(")

ENGINE_PACKAGES = {
    "parsing/": "engine:parse",
    "table/": "engine:table",
    "input/": "engine:container",
    "validator/": "engine:field",
}
CORE_MAIN = "core/src/main/java/org/mobilitydata/gtfsvalidator/"


def to_code(class_name: str) -> str:
    name = re.sub(r"Notice$", "", class_name)
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def classify(path: Path, nested: bool) -> str:
    text = str(path)
    for package, label in ENGINE_PACKAGES.items():
        if CORE_MAIN + package in text:
            return label
    if "/notice/" in text and not nested:
        return "shared-notice-class"
    if text.endswith("Validator.java"):
        return "rule"
    return "other"


def layer_of(origin: str) -> str:
    """Collapse a construction-site origin into one of the spec's three layers."""
    if origin in {"rule", "shared:rule"}:
        return "rule"
    if origin.startswith("shared:engine") or origin == "shared:codegen-or-reflection":
        return "engine"
    if origin.startswith("engine:"):
        return "engine"
    return "geojson-or-standalone"


def source_files(root: Path):
    for path in root.rglob("*.java"):
        text = str(path)
        if "/test/" in text or "/build/" in text:
            continue
        yield path


def scan(root: Path) -> dict[str, dict]:
    notices: dict[str, dict] = {}
    for path in source_files(root):
        text = path.read_text(errors="replace")
        if "extends ValidationNotice" not in text:
            continue
        for match in CLASS_RE.finditer(text):
            annotation, _, static, _, class_name = match.groups()
            nested = bool(static) or path.stem != class_name
            severity = None
            if annotation:
                found = SEVERITY_RE.search(annotation)
                severity = found.group(1) if found else None
            notices[class_name] = {
                "code": to_code(class_name),
                "severity": severity,
                "defined_in": path.relative_to(root).as_posix(),
                "nested_in_validator": nested,
                "origin": classify(path, nested),
            }
    return notices


def resolve_shared(root: Path, notices: dict[str, dict]) -> None:
    """A class in a shared notice/ package is attributed by where it is built."""
    sites: dict[str, set[str]] = collections.defaultdict(set)
    for path in source_files(root):
        text = path.read_text(errors="replace")
        for class_name in CONSTRUCT_RE.findall(text):
            if class_name in notices and path.stem != class_name:
                sites[class_name].add(classify(path, False))

    for class_name, info in notices.items():
        if info["origin"] != "shared-notice-class":
            continue
        found = sorted(sites.get(class_name, {"codegen-or-reflection"}))
        info["origin"] = "shared:" + "+".join(sorted({s.split(":")[0] for s in found}))
        info["constructed_by"] = found


def head_commit(checkout: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def head_date(checkout: Path) -> str:
    """The checkout's own commit date, so `_meta` cannot disagree with what was scanned."""
    return subprocess.run(
        ["git", "-C", str(checkout), "show", "-s", "--format=%cs", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", required=True, help="upstream clone at the pin")
    parser.add_argument("--tag", default="v8.0.1")
    parser.add_argument(
        "--commit-date",
        help="defaults to the checkout's own HEAD date; a constant here would go stale at the "
        "next pin bump and record the wrong date silently",
    )
    parser.add_argument(
        "--measured-on",
        required=True,
        help="ISO date this scan was run; recorded in _meta, not read from the clock",
    )
    args = parser.parse_args()

    root = Path(args.checkout)
    notices = scan(root)
    resolve_shared(root, notices)
    for info in notices.values():
        info["layer"] = layer_of(info["origin"])

    payload = {
        "_meta": {
            "commit": head_commit(root),
            "commit_date": args.commit_date or head_date(root),
            "measured_on": args.measured_on,
            "method": (
                "static scan of classes extending ValidationNotice; "
                "layer inferred from defining path"
            ),
            "tag": args.tag,
            "upstream": "MobilityData/gtfs-validator",
        },
        "notices": {info["code"]: info for info in notices.values()},
    }
    out = out_path(args.tag)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    counts = collections.Counter(i["layer"] for i in notices.values())
    print(f"wrote {out} with {len(notices)} notices")
    print(f"layers: {dict(counts)}")


if __name__ == "__main__":
    main()
