"""Port of commons-validator EmailValidator.getInstance().isValid.

The no-argument getInstance means allowLocal is false and allowTld is false, so
"user@localhost" and "user@com" are both invalid, and the domain's TLD is checked
against the same vendored tables the URL port uses.

Surrounding whitespace is tolerated on both sides, which surprises people: the
top-level pattern is ^\\s*?(.+)@(.+?)\\s*$, so it trims rather than rejects. The
local part is capped at 64 characters. The domain has no cap of its own here:
commons hands it to DomainValidator, whose 253-character limit applies to the
punycode form. All of this is asserted against measured behaviour in
tests/data/validator_oracle.json.
"""

from __future__ import annotations

import re

from gtfs_validator.fieldtypes.domains import is_valid_domain, is_valid_ipv4

MAX_LOCAL_LENGTH = 64

# Reluctant leading \s*? and trailing \s* are why surrounding spaces pass. The
# greedy local group is why "two@at@example.com" fails: the local part becomes
# "two@at", and @ is a special character.
_EMAIL_RE = re.compile(r"\A\s*?(.+)@(.+?)\s*\Z", re.DOTALL | re.ASCII)

_SPECIAL_CHARS = r"\x00-\x1f\x7f()<>@,;:'\\\".\[\]"
_VALID_CHARS = rf"(?:\\.|[^\s{_SPECIAL_CHARS}])"
_QUOTED_USER = r'"[^"]*"'
_WORD = rf"(?:(?:{_VALID_CHARS}|')+|{_QUOTED_USER})"
# Dots separate words and may not lead, trail, or double up.
# re.ASCII again: to Java a non-breaking space is neither trimmed by the pattern
# above nor excluded by [^\s...] here, so it is simply an ordinary local-part
# character.
_USER_RE = re.compile(rf"\A\s*{_WORD}(?:\.{_WORD})*\Z", re.ASCII)

_IP_LITERAL_RE = re.compile(r"\A\[(.*)\]\Z", re.DOTALL)


def _is_valid_domain_part(domain: str) -> bool:
    literal = _IP_LITERAL_RE.match(domain)
    if literal:
        return is_valid_ipv4(literal.group(1))
    return is_valid_domain(domain)


def is_valid_email(value: str) -> bool:
    # commons EmailValidator rejects a trailing dot outright, before the domain
    # check, so user@example.com. is invalid even though the domain part with a
    # root dot would otherwise pass.
    if value.endswith("."):
        return False
    match = _EMAIL_RE.match(value)
    if not match:
        return False
    local, domain = match.groups()
    if len(local) > MAX_LOCAL_LENGTH or not _USER_RE.match(local):
        return False
    return _is_valid_domain_part(domain)
