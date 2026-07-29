"""Port of commons-validator UrlValidator.getInstance().isValid.

Upstream calls exactly that, with default options, so these quirks are the
contract rather than bugs. All of them are measured against the bundled
implementation; see tests/data/validator_oracle.json.

  * schemes are limited to http/https/ftp, case insensitively (ALLOW_ALL_SCHEMES
    is off), so mailto: and a scheme-relative //host are invalid
  * "//" anywhere in the path is invalid (ALLOW_2_SLASHES is off)
  * a host whose TLD is not in the vendored tables is invalid, so
    http://localhost is rejected and http://example.transit is too
  * a path normalising to /.. is invalid, but /a/../b is fine
  * the query may not contain whitespace; the fragment may contain anything
  * trailing whitespace after the authority is tolerated, because it lands in
    the authority's "extra" group which is compared after trimming, while
    leading whitespace is not
"""

from __future__ import annotations

import ipaddress
import re

from gtfs_validator.fieldtypes.domains import is_valid_host, unicode_to_ascii

_URL_RE = re.compile(
    r"\A(?:([^:/?#]+):)?(?://([^/?#]*))?([^?#]*)(?:\?([^#]*))?(?:#(.*))?\Z", re.DOTALL
)
_SCHEME_RE = re.compile(r"\A[a-zA-Z][a-zA-Z0-9+\-.]*\Z")
ALLOWED_SCHEMES = frozenset({"http", "https", "ftp"})

# commons' AUTHORITY_REGEX, transliterated from the jar rather than reconstructed:
#
#   (?:\[([0-9a-fA-F:]+)\]|(?:(?:USERINFO_FIELD)?([\p{Alnum}\-\.]*)))(?::(\d*))?(.*)?
#
# The shape that matters is that the port and the "extra" remainder sit *outside*
# the alternation, so a bracketed IPv6 host gets the same port and trailing-
# whitespace handling as a domain does. Splitting the two branches by hand loses
# that and rejects "http://[::1]:80   /", which commons accepts.
#
# USERINFO_FIELD is one or more userinfo chars, an optional ":password" of the
# same, then "@". Its class [a-zA-Z0-9%-._~!$&'()*+,;=] contains the range %..-
# (& ' ( ) * + , -). A malformed userinfo (a space, a pipe, a bare "@host", a
# second "@") simply fails to match, leaving the "@" in the host charset, which
# excludes it, so the authority lands in "extra" and is rejected.
#
# The host charset is Java's \p{Alnum} plus hyphen and dot, and \p{Alnum} is
# ASCII-only. That is load-bearing: any character left over from a failed IDN
# conversion falls into "extra" and fails.
_USERINFO_CHARS = r"A-Za-z0-9!$%&'()*+,;=._~-"
_USERINFO_FIELD = rf"[{_USERINFO_CHARS}]+(?::[{_USERINFO_CHARS}]*)?@"
_AUTHORITY_RE = re.compile(
    rf"\A(?:\[([0-9a-fA-F:]+)\]|(?:(?:{_USERINFO_FIELD})?([A-Za-z0-9.\-]*)))(?::(\d*))?(.*)?\Z",
    re.DOTALL | re.ASCII,
)
# PATH_REGEX and QUERY_REGEX verbatim, and re.ASCII is doing real work in both.
# Java's \w is [a-zA-Z_0-9] and its \s is ASCII whitespace, because commons sets
# UNICODE_CHARACTER_CLASS nowhere. Without the flag, Python's Unicode-aware \w
# accepts "http://example.com/café", which commons rejects, and its Unicode \S
# rejects a non-breaking space in a query, which commons accepts.
_PATH_RE = re.compile(r"\A(?:/[-\w:@&?=+,.!/~*'%$_;()]*)?\Z", re.ASCII)
_QUERY_RE = re.compile(r"\A\S*\Z", re.ASCII)

MAX_PORT = 65535


def _is_valid_scheme(scheme: str | None) -> bool:
    if scheme is None or not _SCHEME_RE.match(scheme):
        return False
    return scheme.lower() in ALLOWED_SCHEMES


def _is_valid_authority(authority: str | None) -> bool:
    if authority is None:
        return False

    # commons converts the *whole* authority to ASCII before matching anything,
    # so a non-ASCII label's punycode swallows whatever follows it: "例子.中国:80"
    # becomes the single label "xn--:80-u68dy61b" and loses its port, while the
    # all-ASCII "de:8080" passes through and keeps one. Normalising only the host
    # after splitting reverses both verdicts.
    match = _AUTHORITY_RE.match(unicode_to_ascii(authority))
    if not match:
        return False
    ipv6, host, port, extra = match.groups()

    if ipv6 is not None:
        # Measured: http://[::1]:99999 is valid while http://example.com:65536 is
        # not. isValidAuthority range-checks the port only on the domain branch,
        # even though both branches capture it with the same group.
        if not _is_valid_ipv6_literal(ipv6):
            return False
    else:
        if not is_valid_host(host):
            return False
        if port and (not port.isascii() or not port.isdigit() or int(port) > MAX_PORT):
            return False
    return not (extra or "").strip()


def _is_valid_ipv6_literal(inner: str) -> bool:
    """Validate what the bracketed branch captured, as isValidAuthority does.

    The charset that got it here, ``[0-9a-fA-F:]+``, is doing real work rather
    than being a shortcut: it excludes a "%eth0" scope id and the dotted
    IPv4-mapped form, both of which ipaddress accepts and commons rejects
    (``http://[::ffff:192.0.2.1]/`` is invalid upstream). The address itself is
    then checked by InetAddressValidator, so "[gggg::1]" and
    "[1:2:3:4:5:6:7:8:9]" still fail.
    """
    try:
        ipaddress.IPv6Address(inner)
    except ValueError:
        return False
    return True


def _normalize(path: str) -> str:
    """Java URI.normalize, which is not posixpath.normpath.

    The difference is the only one that matters here: normpath collapses a
    leading ".." against the root, turning "/../a" into "/a", while Java retains
    unresolvable leading ".." segments. commons-validator then rejects exactly
    those, so collapsing them would accept a URL upstream rejects.
    """
    resolved: list[str] = []
    for segment in path.split("/")[1:]:
        if segment == ".":
            continue
        if segment == ".." and resolved and resolved[-1] != "..":
            resolved.pop()
            continue
        resolved.append(segment)
    return "/" + "/".join(resolved)


def _is_valid_path(path: str) -> bool:
    if not _PATH_RE.match(path):
        return False
    if path:
        normalised = _normalize(path)
        if normalised.startswith("/../") or normalised == "/..":
            return False
    return "//" not in path


def is_valid_url(value: str) -> bool:
    match = _URL_RE.match(value)
    if not match:
        return False
    scheme, authority, path, query, _fragment = match.groups()
    if not _is_valid_scheme(scheme):
        return False
    if not _is_valid_authority(authority):
        return False
    if not _is_valid_path(path or ""):
        return False
    # A null query is absent, which is fine; an empty one is present and matches.
    return query is None or bool(_QUERY_RE.match(query))
