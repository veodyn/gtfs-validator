#!/usr/bin/env python3
"""Rewrite the golden `report.html` that `tests/test_html_golden.py` pins.

    python tools/regenerate_html_golden.py

Run this only when the page is *meant* to change, and read the diff before
committing. Regenerating to clear a red test converts a caught regression into a
committed one, which is the failure mode every golden file has.

The fixture lives in the test rather than here so there is one definition of what
is rendered. This script imports it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_html_golden import GOLDEN, render_golden  # noqa: E402


def main() -> None:
    page = render_golden()
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    previous = GOLDEN.read_text(encoding="utf-8") if GOLDEN.exists() else None
    GOLDEN.write_text(page, encoding="utf-8")
    if previous is None:
        print(f"wrote {GOLDEN} ({len(page)} bytes)")
    elif previous == page:
        print(f"{GOLDEN} unchanged")
    else:
        print(f"{GOLDEN} CHANGED: {len(previous)} -> {len(page)} bytes. Read the diff.")


if __name__ == "__main__":
    main()
