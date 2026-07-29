"""Port of commons-validator DomainValidator, shared by the URL and email ports.

The load-bearing detail is that a hostname's top-level domain is checked against
vendored tables rather than a shape rule: `example.xyz` is valid and
`example.transit` is not. The tables are generated from the commons-validator
bundled in the pinned jar by tools/build_validator_oracle.py, so they are frozen
at that release. That staleness is deliberate. Refreshing them against today's
IANA registry would make us accept domains upstream rejects, which is a parity
bug rather than an improvement.
"""

from __future__ import annotations

import json
import re
import stringprep
from encodings import idna
from functools import lru_cache
from importlib.resources import files

# Transliterated from commons' DOMAIN_LABEL_REGEX and TOP_LABEL_REGEX, read out of
# the jar by reflection rather than reconstructed: Java's \p{Alnum} and \p{Alpha}
# are ASCII-only, and the {0,61} bound is where the 63-character label cap lives,
# so no separate length check is needed.
#
# There is no punycode special case. A top label is one alpha followed by
# alphanumerics and hyphens, which already admits "xn--fiqs8s" and, importantly,
# the two vendored TLDs carrying an internal hyphen ("xn--vermgensberater-ctb").
# Spelling the ACE form as "xn--" plus alphanumerics rejects those.
_LABEL = r"[a-zA-Z0-9](?>[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
_TOP = r"[a-zA-Z](?>[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
_DOMAIN_RE = re.compile(rf"\A(?:{_LABEL}\.)+({_TOP})\.?\Z")
_IPV4_RE = re.compile(r"\A(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\Z", re.ASCII)

MAX_DOMAIN_LENGTH = 253


# Java's IDN treats all four of these as label separators and writes every one
# back as an ASCII full stop.
LABEL_SEPARATORS = ".\u3002\uff0e\uff61"


def _label_to_ascii(label: str) -> str:
    """RFC 3490 ToASCII for a single label, with Java's prohibitions.

    Python's nameprep and Java's differ in one load-bearing way: RFC 3454 table
    A.1 (code points unassigned in Unicode 3.2) is prohibited by Java and simply
    not checked by Python. Without this test an emoji host punycodes cleanly here
    while IDN.toASCII throws, so commons rejects a URL this would accept.
    """
    if not label.isascii() and any(stringprep.in_table_a1(char) for char in label):
        raise UnicodeError("unassigned code point in Unicode 3.2")
    return idna.ToASCII(label).decode("ascii")


def _idn_to_ascii(value: str) -> str:
    """java.net.IDN.toASCII, which converts label by label and rejoins with dots.

    Transliterated from the JDK loop rather than delegated to str.encode("idna"),
    because the loop never processes a trailing empty label: "münchen.de." keeps
    its dot instead of raising on the empty label after it.
    """
    if len(value) == 1 and value in LABEL_SEPARATORS:
        return "."
    out: list[str] = []
    position = 0
    length = len(value)
    while position < length:
        end = position
        while end < length and value[end] not in LABEL_SEPARATORS:
            end += 1
        out.append(_label_to_ascii(value[position:end]))
        if end != length:
            out.append(".")
        position = end + 1
    return "".join(out)


def unicode_to_ascii(value: str) -> str:
    """commons DomainValidator.unicodeToASCII, which is total rather than partial.

    An input IDN.toASCII rejects comes back unchanged, not as a failure: commons
    catches IllegalArgumentException and returns the original, which then fails
    the ASCII-only domain regex further down. Returning the input is what lets the
    URL port normalise a whole authority without having to special-case failure.
    """
    if value.isascii():
        return value
    try:
        converted = _idn_to_ascii(value)
    except (UnicodeError, ValueError):
        return value
    # Some JDKs drop a trailing separator; commons puts it back.
    if value[-1] in LABEL_SEPARATORS and not converted.endswith("."):
        return converted + "."
    return converted


@lru_cache(maxsize=1)
def _known_tlds() -> frozenset[str]:
    """Every TLD accepted when allowLocal is off, which is how upstream calls it."""
    raw = json.loads(files("gtfs_validator.data").joinpath("tlds.json").read_text())
    return frozenset(
        tld
        for table in ("infrastructure_tlds", "generic_tlds", "country_code_tlds")
        for tld in raw[table]
    )


def is_valid_ipv4(host: str) -> bool:
    match = _IPV4_RE.match(host)
    if not match:
        return False
    return all(len(octet) == 1 or not octet.startswith("0") for octet in match.groups()) and all(
        int(octet) <= 255 for octet in match.groups()
    )


def is_valid_domain(host: str) -> bool:
    if not host:
        return False
    ascii_host = unicode_to_ascii(host)
    if len(ascii_host) > MAX_DOMAIN_LENGTH:
        return False
    match = _DOMAIN_RE.match(ascii_host)
    if not match:
        return False
    return match.group(1).lower() in _known_tlds()


def is_valid_host(host: str) -> bool:
    """DomainValidator first, then InetAddressValidator, as UrlValidator does."""
    return is_valid_domain(host) or is_valid_ipv4(host)
