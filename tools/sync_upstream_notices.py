#!/usr/bin/env python3
"""Regenerate canonical_notices.json from a pinned upstream checkout.

Usage:
    python tools/sync_upstream_notices.py --tag v8.0.1
    python tools/sync_upstream_notices.py --tag v8.0.1 --checkout /path/to/clone

Clones (or reuses) upstream at the given tag, scans every class extending
ValidationNotice, and records its code, severity, and context fields.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

UPSTREAM = "https://github.com/MobilityData/gtfs-validator.git"
OUT = Path(__file__).resolve().parents[1] / "src/gtfs_validator/data/canonical_notices.json"

JSON_TYPES = {
    "String": "string",
    "int": "integer",
    "long": "integer",
    "Integer": "integer",
    "Long": "integer",
    "double": "number",
    "Double": "number",
    "float": "number",
    "Float": "number",
    "boolean": "boolean",
    "Boolean": "boolean",
}

CLASS_RE = re.compile(
    r"(@GtfsValidationNotice\s*\((?:[^()]|\([^()]*\))*\)\s*)?"
    r"(?:public\s+)?(?:static\s+)?(?:final\s+)?class\s+(\w+Notice)\s+extends\s+ValidationNotice",
    re.S,
)
FIELD_RE = re.compile(r"(?:@Nullable\s+)?private final ([\w<>\[\]]+) (\w+);")
SEVERITY_RE = re.compile(r"severity\s*=\s*(?:SeverityLevel\.)?(ERROR|WARNING|INFO)")


def to_code(class_name: str) -> str:
    name = re.sub(r"Notice$", "", class_name)
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def clone(tag: str, dest: Path) -> Path:
    checkout = dest / "upstream"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", tag, UPSTREAM, str(checkout)],
        check=True,
        capture_output=True,
    )
    return checkout


def scan(root: Path) -> dict[str, dict]:
    notices: dict[str, dict] = {}
    for path in root.rglob("*.java"):
        text = path.read_text(errors="replace")
        if "/test/" in str(path) or "extends ValidationNotice" not in text:
            continue
        for match in CLASS_RE.finditer(text):
            annotation, class_name = match.group(1), match.group(2)
            severity_match = SEVERITY_RE.search(annotation or "")
            body = text[match.end() :]
            end = body.find("\n  }")
            fields = FIELD_RE.findall(body[: end if end > 0 else len(body)])
            notices[to_code(class_name)] = {
                "severity": severity_match.group(1) if severity_match else "ERROR",
                "context_fields": {
                    name: JSON_TYPES.get(java_type, "object") for java_type, name in fields
                },
                "defined_in": path.relative_to(root).as_posix(),
            }
    return notices


def head_commit(checkout: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="v8.0.1")
    parser.add_argument(
        "--checkout",
        help="reuse an existing upstream clone instead of cloning (must be at --tag)",
    )
    args = parser.parse_args()

    if args.checkout:
        checkout = Path(args.checkout)
        commit = head_commit(checkout)
        notices = scan(checkout)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            checkout = clone(args.tag, Path(tmp))
            commit = head_commit(checkout)
            notices = scan(checkout)

    payload = {
        "_meta": {"upstream": UPSTREAM, "tag": args.tag, "commit": commit},
        "notices": dict(sorted(notices.items())),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    print(f"wrote {OUT} with {len(notices)} notices")


if __name__ == "__main__":
    main()
