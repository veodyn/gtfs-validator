#!/usr/bin/env python3
"""Record the JDK's display name for every language subtag it knows.

`summary.feedInfo["Feed Language"]` is `feedLang().getDisplayLanguage()`, whose
answer comes from the JDK's CLDR data and from the JVM's default display locale.
Neither is reproducible from Python, so it is measured once and checked in.

The display locale is pinned to `Locale.US` rather than left to the host. On the
pinned jar, one feed carrying `feed_lang=en` reports "English" by default,
"anglais" under `-Duser.language=fr` and the Japanese for English under
`-Duser.language=ja`. Matching that would make our own report depend on the
machine that ran it, which is the opposite of what `-d` exists for. Recorded in
a deliberate difference, with the measurement above.

Usage:
    tools/sync_display_languages.py

Writes src/gtfs_validator/data/display_languages.json. Needs a JDK, at generation
time only. The jar is not involved: this is the JDK's own table.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "tools" / "_oracle" / "DumpDisplayLanguages.java"
OUTPUT = ROOT / "src" / "gtfs_validator" / "data" / "display_languages.json"


def dump() -> dict[str, str]:
    result = subprocess.run(
        ["java", str(SOURCE)],
        capture_output=True,
        text=True,
        check=True,
    )
    names: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        subtag, _, display = line.partition("\t")
        names[subtag] = display
    if not names:
        raise SystemExit("the oracle printed nothing")
    return names


def main() -> int:
    names = dump()
    # A subtag whose display name is the subtag itself is what getDisplayLanguage
    # returns when it has no better answer. Dropping those keeps the table to
    # what it actually knows and makes the fallback in `summary.metadata`
    # (echo the tag) the single place that behaviour is expressed.
    known = {tag: display for tag, display in names.items() if display != tag}
    payload = {
        "_meta": {
            "method": "Locale.getDisplayLanguage(Locale.US)",
            "source": "java.util, the JDK's CLDR data",
            "display_locale": "en-US",
        },
        "languages": dict(sorted(known.items())),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    dropped = len(names) - len(known)
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(known)} subtags, {dropped} self-named dropped")
    for sample in ("en", "eng", "fr", "zh", "qaa"):
        print(f"  {sample}: {known.get(sample, '(echoes the tag)')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
