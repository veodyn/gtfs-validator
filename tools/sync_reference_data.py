#!/usr/bin/env python3
"""Generate the vendored reference tables the field parsers resolve against.

Usage:
    python tools/sync_reference_data.py --jar /tmp/gtfs-validator.jar

Upstream converts these columns with java.util.Currency, java.time.ZoneId,
java.util.Locale.Builder and libphonenumber, all of which ship inside the pinned
jar. Reading the sets out of the jar beats hand-transcribing ISO tables that
would drift from what upstream actually accepts.

Language tags are a grammar rather than a set, so instead of a table this records
the jar's verdict on a corpus and tests/test_fieldtypes_refdata.py asserts our
regex against it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

DUMPER = Path(__file__).resolve().parent / "_oracle" / "DumpRefData.java"
DATA = Path(__file__).resolve().parents[1] / "src/gtfs_validator/data"
TEST_DATA = Path(__file__).resolve().parents[1] / "tests/data"

# Chosen to cover every branch of the BCP 47 grammar: plain language, script,
# region (alphabetic and numeric), variants, extensions, private use, the
# grandfathered irregular tags, and several near-miss malformations.
LANGUAGE_CORPUS = [
    "en",
    "EN",
    "eng",
    "en-US",
    "en-us",
    "zh-Hant",
    "zh-Hant-TW",
    "es-419",
    "de-DE-1901",
    "sl-rozaj-biske",
    "en-US-u-ca-gregory",
    "en-a-bbb-x-a-ccc",
    "x-private",
    "i-klingon",
    "art-lojban",
    "xx",
    "qaa",
    "abcdefgh",
    "abcdefghi",
    "e",
    "",
    "-en",
    "en-",
    "en_US",
    "123",
    "en--US",
    "en-USA",
    "toolongprimarysubtag",
    "en-Latn-US-fonipa-x-eng",
]


def run(jar: str) -> dict[str, list]:
    payload = "".join(tag + "\n" for tag in LANGUAGE_CORPUS)
    result = subprocess.run(
        ["java", "-cp", jar, str(DUMPER)],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    rows: dict[str, list] = {
        "currency": [],
        "zone": [],
        "phoneRegion": [],
        "phoneMeta": [],
        "phoneCode": [],
        "phoneCodeRegion": [],
        "isoCountry": [],
        "phonePattern": [],
        "phoneConst": [],
        "phoneAlpha": [],
        "language": [],
    }
    for line in result.stdout.splitlines():
        kind, _, rest = line.partition("\t")
        if kind in rows:
            rows[kind].append(rest)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jar", required=True, help="the pinned gtfs-validator jar")
    args = parser.parse_args()

    rows = run(args.jar)
    source = {"source": "java.util / libphonenumber, as bundled in gtfs-validator 8.0.1"}

    # currency code -> Currency.getDefaultFractionDigits(), which drives
    # invalid_currency_amount. codes keeps the sorted set for the validity check.
    fraction_digits: dict[str, int] = {}
    for row in rows["currency"]:
        code, _, digits = row.partition("\t")
        fraction_digits[code] = int(digits)
    (DATA / "currencies.json").write_text(
        json.dumps(
            {
                "_meta": source,
                "codes": sorted(fraction_digits),
                "fraction_digits": dict(sorted(fraction_digits.items())),
            },
            indent=2,
        )
        + "\n"
    )
    (DATA / "timezones.json").write_text(
        json.dumps({"_meta": source, "names": sorted(rows["zone"])}, indent=2) + "\n"
    )

    def parse_lengths(pairs: list[str]) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for row in pairs:
            key, _, lengths = row.partition("\t")
            out[key] = [int(n) for n in lengths.split(",") if n]
        return out

    def parse_patterns(pairs: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for row in pairs:
            name, flags, pattern = row.split("\t", 2)
            out[name] = {"flags": int(flags), "pattern": pattern}
        return dict(sorted(out.items()))

    def parse_meta(pairs: list[str]) -> dict[str, dict]:
        """region -> the parse-time metadata isPossibleNumber consults.

        strict_lengths is the IS_POSSIBLE-only length set, which is narrower than
        the probed one because isPossibleNumber also accepts IS_POSSIBLE_LOCAL_ONLY.
        parse() needs the narrow set to decide whether stripping a prefix improved
        the number.
        """
        out: dict[str, dict] = {}
        for row in pairs:
            (
                region,
                code,
                idd,
                national_prefix,
                transform,
                strict,
                pattern,
                lengths,
                local_only,
            ) = row.split("\t")
            out[region] = {
                "country_code": int(code),
                "international_prefix": idd,
                "national_prefix_for_parsing": national_prefix,
                "national_prefix_transform_rule": transform,
                "strict_lengths": [int(n) for n in strict.split(",") if n],
                "national_number_pattern": pattern,
                "possible_lengths": [int(n) for n in lengths.split(",") if n],
                "local_only_lengths": [int(n) for n in local_only.split(",") if n],
            }
        return out

    (DATA / "phone_lengths.json").write_text(
        json.dumps(
            {
                "_meta": {
                    **source,
                    "method": "probed isPossibleNumber per region (national number) "
                    "and per calling code (+CC..., region ZZ), because it is a "
                    "length check that parses a leading + before measuring; the "
                    "per-region prefixes are read from libphonenumber's metadata, "
                    "which no length probe can reveal",
                },
                "regions": dict(sorted(parse_lengths(rows["phoneRegion"]).items())),
                "region_meta": dict(sorted(parse_meta(rows["phoneMeta"]).items())),
                # calling code -> the region parse() resolves it to, whose national
                # prefix and length rules then apply to a +-prefixed number.
                "code_regions": dict(
                    sorted(
                        (row.split("\t", 1) for row in rows["phoneCodeRegion"]),
                        key=lambda kv: int(kv[0]),
                    )
                ),
                "calling_codes": dict(
                    sorted(parse_lengths(rows["phoneCode"]).items(), key=lambda kv: int(kv[0]))
                ),
                # Locale.getISOCountries(): the set upstream's CountryCode accepts,
                # which decides whether a phone is validated at all. Wider than the
                # supported-region set above.
                "iso_countries": sorted(rows["isoCountry"]),
                # The patterns parse() applies before any length check, in Java
                # syntax; the Python side substitutes \p{Nd} and the possessive
                # quantifiers. Each carries its own Java flags, because they are
                # not uniform: compiling the whole set case-insensitively makes
                # SECOND_NUMBER_START_PATTERN's "/x" match "/X". viable_pattern is
                # VALID_PHONE_NUMBER_PATTERN, kept under its old name because it is
                # what isViablePhoneNumber uses.
                "viable_pattern": parse_patterns(rows["phonePattern"])[
                    "VALID_PHONE_NUMBER_PATTERN"
                ]["pattern"],
                "patterns": parse_patterns(rows["phonePattern"]),
                # ALPHA_PHONE_MAPPINGS, keyed by code point in hex. Letters plus
                # ASCII digits only: the alpha path drops every other digit script.
                "alpha_mappings": dict(sorted(row.split("\t", 1) for row in rows["phoneAlpha"])),
                # RFC 3966 markers, which parse() splits a "tel:" URI on.
                "constants": dict(sorted(row.split("\t", 1) for row in rows["phoneConst"])),
            },
            indent=2,
        )
        + "\n"
    )

    verdicts = {}
    for row in rows["language"]:
        verdict, _, tag = row.partition("\t")
        verdicts[tag] = verdict == "true"
    TEST_DATA.mkdir(parents=True, exist_ok=True)
    (TEST_DATA / "language_oracle.json").write_text(
        json.dumps(
            {
                "_meta": {**source, "method": "Locale.Builder().setLanguageTag()"},
                "tags": verdicts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    print(
        f"currencies {len(rows['currency'])}, zones {len(rows['zone'])}, "
        f"phone regions {len(rows['phoneRegion'])}, "
        f"calling codes {len(rows['phoneCode'])}, language cases {len(verdicts)}"
    )


if __name__ == "__main__":
    main()
