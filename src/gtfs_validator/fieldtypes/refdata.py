"""Parsers that resolve against reference data the stdlib carries differently.

Timezones prefer the system tz database via zoneinfo and fall back to the
vendored name list, so a slim container without tzdata behaves like a full one.

Currency codes are a set lookup and case sensitive, because Currency.getInstance
throws on "usd".

Language codes are a *grammar*, not a registry lookup: Locale.Builder accepts any
well-formed BCP 47 tag, so "xx" is valid despite being unassigned. The grammar
includes extlang, extensions, private use, and the grandfathered irregular tags,
all of which a naive "2-3 letters plus optional region" regex rejects.

Phone numbers moved to phones.py: reproducing isPossibleNumber turned out to mean
reproducing libphonenumber's parse(), which is too much to keep beside these.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files

from gtfs_validator.fieldtypes import zones
from gtfs_validator.fieldtypes.scalars import ParseError

# RFC 5646 langtag. Case insensitive, matching Locale.Builder.
_LANGUAGE = r"(?:[a-z]{2,3}(?:-[a-z]{3}){0,3}|[a-z]{4}|[a-z]{5,8})"
_SCRIPT = r"(?:-[a-z]{4})?"
_REGION = r"(?:-(?:[a-z]{2}|[0-9]{3}))?"
_VARIANT = r"(?:-(?:[a-z0-9]{5,8}|[0-9][a-z0-9]{3}))*"
_EXTENSION = r"(?:-[0-9a-wy-z](?:-[a-z0-9]{2,8})+)*"
_PRIVATE_USE = r"(?:-x(?:-[a-z0-9]{1,8})+)?"
_LANGTAG_RE = re.compile(
    rf"\A{_LANGUAGE}{_SCRIPT}{_REGION}{_VARIANT}{_EXTENSION}{_PRIVATE_USE}\Z",
    re.IGNORECASE,
)
_PRIVATE_ONLY_RE = re.compile(r"\Ax(?:-[a-z0-9]{1,8})+\Z", re.IGNORECASE)

# Irregular grandfathered tags cannot be expressed by the langtag grammar and are
# accepted by name. The regular ones already parse as langtags.
_GRANDFATHERED = frozenset(
    {
        "en-gb-oed",
        "i-ami",
        "i-bnn",
        "i-default",
        "i-enochian",
        "i-hak",
        "i-klingon",
        "i-lux",
        "i-mingo",
        "i-navajo",
        "i-pwn",
        "i-tao",
        "i-tay",
        "i-tsu",
        "sgn-be-fr",
        "sgn-be-nl",
        "sgn-ch-de",
    }
)


@lru_cache(maxsize=4)
def _vendored(name: str, key: str) -> frozenset[str]:
    raw = json.loads(files("gtfs_validator.data").joinpath(name).read_text())
    return frozenset(raw[key])


def parse_timezone(value: str) -> str | ParseError:
    """ZoneId.of, which is an exact-name lookup against the JVM's tz database.

    The vendored name list is authoritative rather than a fallback, and zoneinfo
    is deliberately not consulted for validity. zoneinfo resolves names through
    the filesystem, so on a case-insensitive one (macOS by default)
    "america/new_york" loads successfully while ZoneId.of rejects it. Deferring
    to zoneinfo would make a notice's presence depend on the host OS.
    """
    if not value:
        return ParseError("empty timezone")
    # The normalised ID rather than the feed's spelling: upstream stores a parsed
    # ZoneId, so two spellings of one offset must compare and report as one value.
    # See fieldtypes/zones.py for the oracled table.
    normalized = zones.normalize(value, _vendored("timezones.json", "names"))
    if normalized is None:
        return ParseError("unknown timezone")
    return normalized


def parse_currency_code(value: str) -> str | ParseError:
    # Currency.getInstance is case sensitive: "usd" throws.
    if value in _vendored("currencies.json", "codes"):
        return value
    return ParseError("unknown currency code")


def parse_language_code(value: str) -> str | ParseError:
    lowered = value.lower()
    if lowered in _GRANDFATHERED or _PRIVATE_ONLY_RE.match(value):
        return value
    if _LANGTAG_RE.match(value):
        return value
    return ParseError("not a well-formed BCP 47 language tag")
