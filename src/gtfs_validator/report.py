"""Serializers for report.json and system_errors.json.

The notices array is sorted by ``code + severity_ordinal`` and each entry's
samples keep discovery order, both matching upstream's
ValidationReportDeserializer.serialize.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

from .notices import NoticeContainer


def _entries(container: NoticeContainer) -> list[dict]:
    entries = []
    for key, notices in container.grouped().items():
        first = notices[0]
        entries.append(
            {
                "code": first.code,
                "severity": first.severity.name,
                "totalNotices": container.count_for(key),
                "sampleNotices": [
                    _defined(n.context) for n in notices[: container.max_exports_per_type]
                ],
            }
        )
    return entries


def _defined(context: dict) -> dict:
    """Drop null context values, which is what upstream's Gson does.

    Notice.GSON is built without serializeNulls, so a notice field holding null
    is absent from the report rather than present as null. Writing it as null
    would be a context-key divergence on every notice with an optional field.
    """
    return {key: value for key, value in context.items() if value is not None}


def build_report(container: NoticeContainer) -> dict:
    return {"notices": _entries(container)}


def build_system_errors(container: NoticeContainer) -> dict:
    return {"notices": _entries(container)}


def dumps_json(payload: dict, *, pretty: bool = False) -> str:
    """Serialise a report the way Gson does, compact unless `-p` was given.

    Two things here are byte-level parity rather than taste, both measured
    against the jar's own output:

    - **Compact means no spaces at all.** Gson writes `{"a":1,"b":2}`, where
      Python's default would write `{"a": 1, "b": 2}`. `-p` switches to Gson's
      pretty printer, whose two-space indent and `": "` separator are what
      `indent=2` already produces.
    - **No trailing newline.** `Files.write` puts the string's bytes down and
      stops. We appended one until 2026-07-29, which was one byte of difference
      on every report ever written.

    ensure_ascii=False leaves stop names and agency names as themselves, so the
    encoding has to be stated at the write: on a non-UTF-8 locale `write_text`
    would otherwise pick the locale codec and raise on the first Japanese stop
    name.

    allow_nan=False rejects a non-finite float rather than writing bare NaN or
    Infinity, which is not valid JSON: a latitude of "NaN" parses in Java-style
    float parsing and would otherwise reach a context value. Such a value is
    rendered to its string form before it gets here (see _json_safe).
    """
    text = json.dumps(
        _json_safe(payload),
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    # Unquote the marked decimals: "\ufffe-1.20\ufffe" becomes the bare number -1.20.
    return re.sub(f'"{_DECIMAL_MARK}([^"]*){_DECIMAL_MARK}"', r"\1", text)


def write_text(text: str, path: Path) -> None:
    """Write one report, creating the output directory as upstream does."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(payload: dict, path: Path) -> None:
    """Indented, newline-terminated. Kept for callers that want a readable file."""
    write_text(dumps_json(payload, pretty=True) + "\n", path)


# A lone surrogate cannot be encoded as UTF-8. json.loads accepts one from an
# escape like \ud800, so a feed can put it in a notice's context, and write_json
# then dies with UnicodeEncodeError before either report is written: the tool
# produces nothing at all for a feed it should merely have complained about.
# Each is replaced with U+FFFD, which is what the CSV reader already substitutes
# for a malformed byte, so one unrepresentable character reads the same wherever it
# came from.
_SURROGATES = range(0xD800, 0xE000)
REPLACEMENT = "\ufffd"


def _encodable(value: str) -> str:
    if not any(ord(char) in _SURROGATES for char in value):
        return value
    return "".join(REPLACEMENT if ord(char) in _SURROGATES else char for char in value)


# A Decimal has to reach the file as a bare JSON number carrying its own scale, and `json` gives
# no hook for that: `default=` re-encodes whatever it returns, and the encoder calls
# `float.__repr__` unbound, so even a float subclass cannot override its own rendering. So a
# Decimal is dumped as a uniquely marked string and the marks are stripped from the finished text.
# U+FFFE cannot appear in a value: the CSV reader replaces every non-character before one reaches
# a notice, and the marker is matched only in the exact quoted shape written here.
_DECIMAL_MARK = "\ufffe"


def _json_safe(value: object) -> object:
    """Render non-finite floats as their Java toString, and a Decimal as its own digits."""
    if isinstance(value, Decimal):
        # str(Decimal) is BigDecimal.toString: it keeps the scale the feed wrote, so -1.20 stays
        # -1.20 and -1e-400 stays -1E-400 rather than underflowing to -0.0.
        return f"{_DECIMAL_MARK}{value}{_DECIMAL_MARK}"
    if isinstance(value, str):
        return _encodable(value)
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        if value != value:
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value
