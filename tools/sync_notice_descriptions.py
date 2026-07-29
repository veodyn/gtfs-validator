#!/usr/bin/env python3
"""Render each notice's documentation to the HTML report.html shows.

`NoticeView.getDescription()` is `getCombinedDocumentation()` run through
flexmark: the short summary, then a blank line and the additional documentation
when there is any. `th:utext` drops the result into the page unescaped, so
byte-identity for report.html needs flexmark's exact output, down to which
paragraphs it wraps and where it puts newlines.

Reimplementing a Markdown renderer to match another one exactly is the kind of
transcription this project keeps losing to. So the rendering is measured once
per code at the pin, with flexmark taken out of the jar, and checked in.

Usage:
    tools/sync_notice_descriptions.py --jar /private/tmp/gtfs-validator.jar

Reads src/gtfs_validator/data/notice_schema.json for the inputs, so run
sync_notice_schema.py first. Writes notice_descriptions.json. Needs a JDK.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tools" / "_oracle" / "RenderMarkdown.java"
SCHEMA = ROOT / "src" / "gtfs_validator" / "data" / "notice_schema.json"
OUTPUT = ROOT / "src" / "gtfs_validator" / "data" / "notice_descriptions.json"
KEY = "###KEY "


def combined(entry: dict) -> str:
    """`getCombinedDocumentation()`: summary, then the extra docs after a blank line."""
    docs = entry.get("shortSummary") or ""
    extra = entry.get("description")
    if extra:
        docs += "\n\n" + extra
    return docs


def render(jar: Path, documents: dict[str, str]) -> dict[str, str]:
    payload = "".join(f"{KEY}{code}\n{text}\n" for code, text in documents.items())
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / "input.md"
        source.write_text(payload, encoding="utf-8")
        result = subprocess.run(
            ["java", "-cp", str(jar), str(SOURCE), str(source)],
            capture_output=True,
            text=True,
            check=True,
        )

    rendered: dict[str, str] = {}
    key: str | None = None
    body: list[str] = []
    for line in result.stdout.split("\n"):
        if line.startswith(KEY):
            if key is not None:
                rendered[key] = "\n".join(body)
            key = line[len(KEY) :]
            body = []
        else:
            body.append(line)
    if key is not None:
        rendered[key] = "\n".join(body)
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path, help="the pinned upstream CLI jar")
    args = parser.parse_args()
    if not args.jar.is_file():
        raise SystemExit(f"no jar at {args.jar}")

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    documents = {code: combined(entry) for code, entry in schema.items()}
    rendered = render(args.jar, documents)

    missing = sorted(set(documents) - set(rendered))
    if missing:
        raise SystemExit(f"flexmark returned nothing for {len(missing)} codes: {missing[:5]}")

    payload = {
        "_meta": {
            "method": "NoticeView.getDescription(), flexmark Parser + HtmlRenderer at defaults",
            "source": "gtfs-validator 8.0.1",
        },
        "descriptions": dict(sorted(rendered.items())),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(rendered)} codes")
    sample = rendered["missing_recommended_file"]
    print(f"  missing_recommended_file: {sample!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
