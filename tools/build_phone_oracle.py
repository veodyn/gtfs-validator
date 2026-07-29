#!/usr/bin/env python3
"""Record what libphonenumber says about a corpus of phone numbers.

Usage:
    python tools/build_phone_oracle.py --jar /tmp/gtfs-validator.jar

Upstream calls PhoneNumberUtil.getInstance().isPossibleNumber(value, countryCode),
and libphonenumber is a large library we cannot depend on at runtime. The port in
src/gtfs_validator/fieldtypes/phones.py is a length model driven by tables measured from
the jar, so it can only be trusted as far as it has been measured. This asks the
real implementation about a corpus that varies region, digit script, punctuation
and national-prefix shape, and checks the answers in as a fixture.

Re-run only when the corpus grows or the pinned jar changes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ORACLE_SOURCE = Path(__file__).resolve().parent / "_oracle" / "PhoneOracle.java"
OUT = Path(__file__).resolve().parents[1] / "tests/data/phone_oracle.json"

# Regions worth separating: a large NANP region whose calling code doubles as its
# national prefix, two European regions with different length sets, a real ISO
# country libphonenumber has no metadata for, and the non-ISO and sentinel codes.
REGIONS = ["US", "GB", "FR", "DE", "AU", "AQ", "QQ", "ZZ", "us", ""]

# Digit scripts libphonenumber normalises through Character.digit(c, 10). A port
# that counts only ASCII digits reads all of these as empty. Each script is built
# from its base code point rather than written as a literal: the glyphs are
# confusable with ASCII digits in a source file, and one wrong character in a
# fixture generator is invisible.
ARABIC_INDIC = "".join(chr(0x0660 + n) for n in range(10))
DEVANAGARI = "".join(chr(0x0966 + n) for n in range(10))
FULLWIDTH = "".join(chr(0xFF10 + n) for n in range(10))
# Osmanya is a supplementary-plane decimal script, which is the whole point.
OSMANYA = "".join(chr(0x104A0 + n) for n in range(10))
FULLWIDTH_PLUS = "\uff0b"
FULLWIDTH_PARENS = ("\uff08", "\uff09")


def _translate(digits: str, script: str) -> str:
    return "".join(script[int(c)] if c.isdigit() else c for c in digits)


VALUES = [
    # Plain national numbers of assorted lengths.
    "2025550173",
    "202555017",
    "20255501730",
    "12025550173",
    "120255501730",
    "17654321",
    "1234567",
    "12345",
    "1",
    "",
    " ",
    # Punctuation and formatting libphonenumber tolerates.
    "202-555-0173",
    "(202) 555-0173",
    "1-202-555-0173",
    "+1 202-555-0173",
    "+1 (202) 555-0173",
    "202.555.0173",
    "202 555 0173",
    "  2025550173  ",
    # International forms, which ignore the passed region.
    "+442079460958",
    "+44 20 7946 0958",
    "+33 1 42 68 53 00",
    "+61 2 9374 4000",
    "+999 12345",
    "+0 12345",
    "+",
    "++12025550173",
    "0012025550173",
    "011 44 20 7946 0958",
    # parseHelper catches an unresolvable calling code after a plus and retries
    # with the plus removed, which lets the region's dialling prefix have a go.
    "+011 44 20 7946 0958",
    "+011442079460958",
    "+00 44 20 7946 0958",
    "+2025550173",
    # Extensions, which are stripped before the length check.
    "2025550173 ext. 42",
    "2025550173x42",
    "+1 202-555-0173 ext 9",
    # Letters, which parse only in the vanity-number positions.
    "+abc1 202-555-0173",
    "abc",
    "1-800-FLOWERS",
    "2025550173abc",
    # Non-ASCII digit scripts, whole and mixed.
    _translate("2025550173", ARABIC_INDIC),
    _translate("12025550173", ARABIC_INDIC),
    "+1 202-555-0173" + ARABIC_INDIC[1],
    _translate("2025550173", DEVANAGARI),
    _translate("2025550173", FULLWIDTH),
    FULLWIDTH_PLUS + _translate("12025550173", FULLWIDTH),
    FULLWIDTH_PLUS + _translate("442079460958", FULLWIDTH),
    # RFC 3966 "tel:" URIs, whose parameters parse() strips before it checks
    # viability. A phone-context holding a calling code joins the number; a domain
    # one is dropped. This build has no phone-context validity check, so an absurd
    # context is ignored rather than fatal.
    "tel:+1-202-555-0173",
    "tel:202-555-0173",
    "tel:202-555-0173;phone-context=example.com",
    "tel:202-555-0173;phone-context=+1",
    "tel:202-555-0173;phone-context=!!!",
    "tel:202-555-0173;phone-context=",
    "tel:202-555-0173;phone-context=+1;isub=99",
    "tel:202-555-0173;isub=12345",
    "tel:202-555-0173;ext=99",
    "tel:2025550173;phone-context=example.com;isub=1",
    "tel:99;phone-context=+1202555017",
    ";phone-context=+1",
    "202-555-0173;phone-context=example.com",
    # SECOND_NUMBER_START_PATTERN is case sensitive, so "/x" cuts and "/X" does not.
    "2025550173/x1234567890",
    "2025550173/X1234567890",
    "2025550173/ x1234567890",
    # normalizeDigitsOnly iterates UTF-16 units, so a supplementary-plane digit
    # arrives as two surrogate halves and is dropped entirely, even though the
    # viability pattern matched it by code point a step earlier.
    _translate("2025550173", OSMANYA),
    "+1" + _translate("2025550173", OSMANYA),
    # ALPHA_PHONE_MAPPINGS carries only the letters and the ASCII digits, so three
    # letters put the number on a path where every other digit script vanishes.
    _translate("1234567", FULLWIDTH) + "ABC",
    _translate("1234567", ARABIC_INDIC) + "ABC",
    "1234567ABC",
    # Fullwidth punctuation, which the viability pattern admits.
    FULLWIDTH_PLUS
    + _translate("1", FULLWIDTH)
    + FULLWIDTH_PARENS[0]
    + _translate("202", FULLWIDTH)
    + FULLWIDTH_PARENS[1]
    + _translate("5550173", FULLWIDTH),
]


def ask(jar: str, cases: list[tuple[str, str]]) -> dict[str, dict[str, bool]]:
    payload = "".join(f"{region}\t{value}\n" for region, value in cases)
    result = subprocess.run(
        ["java", "-cp", jar, str(ORACLE_SOURCE)],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    verdicts: dict[str, dict[str, bool]] = {}
    for line in result.stdout.splitlines():
        region, verdict, value = line.split("\t", 2)
        verdicts.setdefault(region, {})[value] = verdict == "true"
    return verdicts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jar", required=True, help="the pinned gtfs-validator jar")
    args = parser.parse_args()

    # A value carrying a tab or a newline would corrupt the wire format, and the
    # empty value cannot survive a line-oriented protocol at all.
    for value in VALUES:
        if "\t" in value or "\n" in value:
            raise SystemExit(f"corpus value is not line-safe: {value!r}")

    cases = [(region, value) for region in REGIONS for value in VALUES]
    verdicts = ask(args.jar, cases)

    missing = [(r, v) for r, v in cases if v not in verdicts.get(r, {})]
    if missing:
        raise SystemExit(f"oracle did not answer for: {missing}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "_meta": {
                    "source": "com.google.i18n.phonenumbers.PhoneNumberUtil, "
                    "as bundled in gtfs-validator 8.0.1",
                    "method": "isPossibleNumber(value, region)",
                    "note": "the raw libphonenumber verdict; upstream's unknown-country "
                    "gate is applied by the caller, not recorded here",
                },
                "possible": verdicts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    total = sum(len(v) for v in verdicts.values())
    accepted = sum(sum(v.values()) for v in verdicts.values())
    print(f"phone: {total} cases across {len(verdicts)} regions, {accepted} possible")


if __name__ == "__main__":
    main()
