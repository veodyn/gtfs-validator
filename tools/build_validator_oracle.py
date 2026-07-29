#!/usr/bin/env python3
"""Record what commons-validator actually says about a corpus of URLs and emails.

Usage:
    python tools/build_validator_oracle.py --jar /tmp/gtfs-validator.jar

Upstream calls UrlValidator.getInstance().isValid and
EmailValidator.getInstance().isValid, both bundled inside the validator jar. Our
ports have to agree with them exactly, and commons-validator has quirks that
neither urllib.parse nor a hand-written regex reproduces. Rather than guess at
them, this asks the real implementation and checks the answers in as a fixture,
so tests/test_urls.py and tests/test_emails.py assert measured behaviour.

Re-run only when the corpus grows or the pinned jar changes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ORACLE_SOURCE = Path(__file__).resolve().parent / "_oracle" / "Oracle.java"
TLD_SOURCE = Path(__file__).resolve().parent / "_oracle" / "DumpTlds.java"
OUT = Path(__file__).resolve().parents[1] / "tests/data/validator_oracle.json"
TLD_OUT = Path(__file__).resolve().parents[1] / "src/gtfs_validator/data/tlds.json"

URLS = [
    # Plain acceptance
    "http://example.com",
    "https://example.com",
    "https://example.com/",
    "ftp://files.example.com/pub",
    "https://example.com/path/to/feed.zip",
    "https://example.com/path?query=1",
    "https://example.com/path?query=1#fragment",
    "https://example.com#fragment",
    "https://sub.domain.example.co.uk:8443/a/b",
    "http://192.168.1.1/gtfs",
    "https://example.com/a%20b",
    "https://example.com/a+b",
    "https://example.com:80",
    "http://EXAMPLE.COM",
    "http://example.travel",
    "http://example.museum",
    # Scheme handling
    "example.com",
    "//example.com",
    "mailto:someone@example.com",
    "gopher://example.com",
    "HTTP://example.com",
    "htp://example.com",
    "://example.com",
    # Host handling
    "http://localhost",
    "http://localhost:8080/gtfs",
    "http://.example.com",
    "http://example..com",
    "http://-example.com",
    "http://example-.com",
    "http://example.c",
    "http://256.256.256.256",
    "http://1.2.3",
    "http://1.2.3.4.5",
    "http://0.0.0.0",
    "http://example.com:port",
    "http://example.com:-1",
    "http://example.com:65536",
    # Path handling
    "http://example.com//double",
    "http://example.com/a//b",
    "http://example.com/../a",
    "http://example.com/a b",
    # Userinfo and IPv6, which commons accepts
    "http://user:pass@example.com/",
    "http://user@example.com/",
    "http://[::1]/",
    "http://[2001:db8::1]:8080/x",
    "http://[not-ipv6]/",
    # Userinfo the commons grammar rejects: a space or pipe is not a userinfo
    # char, an empty userinfo before @ needs one, and a second @ leaves it in the
    # host. These distinguish the real grammar from an "anything before @" strip.
    "http://user name@example.com/",
    "http://us|er@example.com/",
    "http://a@b@example.com/",
    "http://@example.com/",
    "http://user%20name@example.com/",
    "http://user@[::1]/",
    # The bracketed branch is "[0-9a-fA-F:]+" plus a real address check, so a scope
    # id and the dotted IPv4-mapped form are rejected even though ipaddress accepts
    # them, and a malformed address is rejected even though the charset allows it.
    "http://[fe80::1%eth0]/",
    "http://[fe80::1%25eth0]/",
    "http://[fe80::1%bad zone]/",
    "http://[::ffff:192.0.2.1]/",
    "http://[fffff::1]/",
    "http://[1:2:3:4:5:6:7:8]/",
    "http://[1:2:3:4:5:6:7:8:9]/",
    "http://[gggg::1]/",
    "http://[::]/",
    "http://[:::]/",
    "http://[]/",
    "http://[::1]x/",
    # The port range is checked on the domain branch but not the bracketed one.
    "http://[::1]:99999",
    "http://[::1]:-1",
    "http://[::1]:port",
    "http://example.com:65535",
    "http://example.com:0",
    # Internationalized domain names. commons runs DomainValidator.unicodeToASCII
    # over the *whole* authority before splitting it, so the punycode of a label
    # swallows a ":" or "@" that follows a non-ASCII one: "例子.中国:80" becomes the
    # single label "xn--:80-..." and loses its port. An ASCII label is passed
    # through untouched, which is why "münchen.de:8080" keeps its port.
    "https://例子.中国",
    "https://münchen.de/",
    "http://例子.中国:80/",
    "https://例子.中国/path",
    "http://user@例子.中国/",
    "https://münchen.de:8080/",
    "http://user@münchen.de/",
    # Java's IDN.toASCII runs nameprep with unassigned code points prohibited, so
    # a character absent from Unicode 3.2 throws and commons keeps the input
    # unchanged, which then fails the domain regex. Python's idna codec has no
    # such check and happily punycodes it.
    "http://a\U0001f984b.com/",
    "http://münchen。de/",
    "http://münchen.de./",
    # A punycoded TLD is not a special case in commons at all: TOP_LABEL_REGEX is
    # "\p{Alpha}(?>[\p{Alnum}-]{0,61}\p{Alnum})?", one alpha then alnum-or-hyphen.
    # Two vendored TLDs carry an internal hyphen, so a rule that special-cases
    # "xn--" followed by alphanumerics alone rejects a domain upstream accepts.
    "http://example.xn--vermgensberater-ctb",
    "http://example.vermögensberater",
    "http://example.xn--vermgensberater-ctb/path",
    # The port and the "extra" remainder are shared by both authority branches, so
    # a bracketed IPv6 host tolerates trailing whitespace exactly as a domain does.
    "http://[::1]:80   /",
    "http://[::1]:80 ",
    "http://example.com:80   /",
    "http://[::1]   /",
    # Java's \d, \w and \s are ASCII-only unless UNICODE_CHARACTER_CLASS is set,
    # and commons sets it nowhere. Python's are Unicode-aware, so a transliterated
    # class silently widens PATH_REGEX's \w and narrows QUERY_REGEX's \S. An
    # accented path is the realistic case here; the rest pin the boundary.
    "http://example.com/café",
    "http://example.com/日本",
    "http://example.com/aéb",
    "http://example.com/\u0660",
    "http://example.com/?a=\xa0b",
    # A supplementary-plane decimal digit is \p{Nd} but not [0-9], and IDN
    # conversion rejects it (unassigned in Unicode 3.2), so it survives into the
    # authority and must not be read as a port.
    "http://[::1]:\U000104a1/",
    "http://[::1]:1\U000104a1/",
    "http://example.com:\U000104a1/",
    # Degenerate
    "",
    " ",
    " http://example.com",
    "http://example.com ",
    "http://",
    "http:///path",
]

EMAILS = [
    "someone@example.com",
    "first.last@example.co.uk",
    "user+tag@example.com",
    "u@sub.example.com",
    '"quoted local"@example.com',
    "a@example.com",
    "UPPER@EXAMPLE.COM",
    "user_name@example.com",
    "user-name@example.com",
    "user@example.travel",
    "user@[192.168.1.1]",
    "",
    "no-at-sign",
    "@example.com",
    "someone@",
    "someone@localhost",
    "someone@com",
    "someone@example..com",
    "some one@example.com",
    "someone@-example.com",
    "someone@example-.com",
    "someone..double@example.com",
    ".leading@example.com",
    "trailing.@example.com",
    "a" * 65 + "@example.com",
    "a" * 64 + "@example.com",
    "someone@" + "d" * 250 + ".com",
    "two@at@example.com",
    " someone@example.com",
    "someone@example.com ",
    "user@example.com.",
    "user@例子.中国",
    "user@münchen.de",
    "user@[192.168.1.1]",
    "user@a\U0001f984b.com",
    "user@münchen。de",
    "user@example.xn--vermgensberater-ctb",
    "user@example.vermögensberater",
    # ASCII-only \s again: a non-breaking space is not whitespace to Java, so it
    # neither separates a local part nor gets trimmed from the end.
    "us\xa0er@example.com",
    "\xa0someone@example.com",
    "someone@example.com\xa0",
    "café@example.com",
    # Supplementary-plane labels, which punycode to a valid ASCII domain. Kept to
    # pin that the domain length precheck is not what decides these.
    "user@" + ".".join("\U00010400" * 50 for _ in range(3)) + ".com",
    "user@" + ".".join("\U00010400" * 60 for _ in range(3)) + ".com",
]


def ask(jar: str, cases: list[tuple[str, str]]) -> dict[str, dict[str, bool]]:
    payload = "".join(f"{kind}\t{value}\n" for kind, value in cases)
    result = subprocess.run(
        ["java", "-cp", jar, str(ORACLE_SOURCE)],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    verdicts: dict[str, dict[str, bool]] = {"url": {}, "email": {}}
    for line in result.stdout.splitlines():
        kind, verdict, value = line.split("\t", 2)
        verdicts[kind][value] = verdict == "true"
    return verdicts


def dump_tlds(jar: str) -> None:
    """Vendor the TLD tables DomainValidator checks a hostname's suffix against.

    Both validators reject a host whose top-level domain is absent from these
    arrays, so a port without them accepts domains upstream rejects: .xyz is
    accepted and .transit is not. The list is frozen at whatever commons-validator
    shipped, and that staleness is the contract rather than something to refresh
    against today's IANA registry.
    """
    result = subprocess.run(
        ["java", "-cp", jar, str(TLD_SOURCE)],
        capture_output=True,
        text=True,
        check=True,
    )
    tables: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        table, value = line.split("\t", 1)
        tables.setdefault(table.lower(), []).append(value)

    TLD_OUT.write_text(
        json.dumps(
            {
                "_meta": {
                    "source": "org.apache.commons.validator.routines.DomainValidator, "
                    "as bundled in gtfs-validator 8.0.1",
                    "note": "local TLDs apply only when allowLocal is set, which "
                    "upstream never sets",
                },
                **{name: sorted(values) for name, values in tables.items()},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    total = sum(len(v) for k, v in tables.items() if k != "local_tlds")
    print(f"wrote {TLD_OUT} with {total} non-local TLDs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jar", required=True, help="the pinned gtfs-validator jar")
    args = parser.parse_args()

    dump_tlds(args.jar)
    cases = [("url", u) for u in URLS] + [("email", e) for e in EMAILS]
    verdicts = ask(args.jar, cases)

    # A value containing a tab or newline would corrupt the wire format, and a
    # dropped case would silently weaken the fixture. Fail loudly instead.
    missing = [v for k, v in cases if v not in verdicts[k]]
    if missing:
        raise SystemExit(f"oracle did not answer for: {missing}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "_meta": {
                    "source": "org.apache.commons.validator.routines, "
                    "as bundled in gtfs-validator 8.0.1",
                    "method": "UrlValidator.getInstance().isValid / "
                    "EmailValidator.getInstance().isValid",
                },
                "url": verdicts["url"],
                "email": verdicts["email"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    for kind in ("url", "email"):
        accepted = sum(verdicts[kind].values())
        print(f"{kind}: {len(verdicts[kind])} cases, {accepted} accepted")


if __name__ == "__main__":
    main()
