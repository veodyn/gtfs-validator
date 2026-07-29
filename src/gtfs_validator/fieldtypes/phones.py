"""Port of libphonenumber's isPossibleNumber, which upstream calls per phone cell.

DefaultFieldValidator.validatePhoneNumber calls
PhoneNumberUtil.getInstance().isPossibleNumber(value, countryCode), and that is
not the length check its name suggests: it *parses* first, and parse() rewrites
the number several times before anything is measured. Skipping those rewrites
gets roughly a quarter of a measured corpus wrong, so this follows parseHelper
step by step:

  1. extractPossibleNumber trims junk before the first digit or plus and after
     the last letter or digit.
  2. isViablePhoneNumber rejects what does not look like a number at all.
  3. An unsupported default region is only allowed when the number starts with a
     plus, which is why a real ISO country with no metadata ("AQ") fails.
  4. The extension is stripped.
  5. A leading plus, or the region's international dialling prefix, marks the
     number as carrying its own country calling code.
  6. Letters are mapped to digits when there are three or more of them, and every
     Unicode decimal digit is folded to ASCII.
  7. A leading country calling code or national prefix is stripped, but only when
     doing so turns an impossible number into a possible one.

The tables and regexes all come from the jar via tools/sync_reference_data.py,
and the verdicts are asserted against tests/data/phone_oracle.json.
"""

from __future__ import annotations

import re

from gtfs_validator.fieldtypes.phone_parsing import (
    build_national_number_for_parsing,
    extract_country_code,
    is_viable_phone_number,
    match_java_regex,
    plus_prefix_length,
    starts_with_plus,
    strip_extension,
    strip_international_prefix,
)
from gtfs_validator.fieldtypes.phone_tables import (
    FROM_DEFAULT_COUNTRY,
    INVALID_LENGTH,
    IS_POSSIBLE,
    IS_POSSIBLE_LOCAL_ONLY,
    MAX_INPUT_STRING_LENGTH,
    MAX_LENGTH_FOR_NSN,
    MIN_LENGTH_FOR_NSN,
    NON_GEOGRAPHICAL_REGION,
    TOO_LONG,
    TOO_SHORT,
    UNKNOWN_COUNTRY,
    iso_countries,
    java_regex,
    tables,
)
from gtfs_validator.javatext import utf16_length


def _match_national_number(number: str, meta: dict) -> bool:
    raw = meta.get("national_number_pattern")
    return bool(raw) and match_java_regex(raw, number)


def _test_number_length(number: str, meta: dict) -> str:
    possible = meta["possible_lengths"]
    if not possible:
        return INVALID_LENGTH
    actual = len(number)
    if actual in meta["local_only_lengths"]:
        return IS_POSSIBLE_LOCAL_ONLY
    if possible[0] == actual:
        return IS_POSSIBLE
    if possible[0] > actual:
        return TOO_SHORT
    if possible[-1] < actual:
        return TOO_LONG
    return IS_POSSIBLE if actual in possible[1:] else INVALID_LENGTH


def _strip_national_prefix(number: str, meta: dict) -> str:
    """maybeStripNationalPrefixAndCarrierCode, without the carrier code.

    The strip is refused when the number already matched the region's pattern and
    the remainder would not, which is what keeps a valid number from being eaten
    by a national prefix that happens to be its first digit.
    """
    prefix = meta["national_prefix_for_parsing"]
    if not number or not prefix:
        return number
    match = re.compile(java_regex(prefix)).match(number)
    if not match:
        return number
    transform = meta["national_prefix_transform_rule"]
    groups = match.groups()
    if transform and groups and groups[-1] is not None:
        # A transform rule rewrites rather than removes; the rule is a Java
        # replacement template, whose $1 form is Python's \1.
        rewritten = match.expand(re.sub(r"\$(\d)", r"\\\1", transform)) + number[match.end() :]
        if _match_national_number(number, meta) and not _match_national_number(rewritten, meta):
            return number
        return rewritten
    if _match_national_number(number, meta) and not _match_national_number(
        number[match.end() :], meta
    ):
        return number
    return number[match.end() :]


def _region_meta(region: str) -> dict | None:
    return tables()["region_meta"].get(region)


def _metadata_for_country_code(code: int) -> dict | None:
    """The metadata isPossibleNumber measures against, keyed by calling code.

    A non-geographical code resolves to region "001", whose metadata is not in the
    per-region table; the probed length set for that calling code stands in.
    """
    region = tables()["code_regions"].get(str(code))
    if region is None or region == NON_GEOGRAPHICAL_REGION:
        return None
    return _region_meta(region)


# maybeExtractCountryCode's three outcomes. The two failures are distinct because
# only INVALID_COUNTRY_CODE is retried; TOO_SHORT_AFTER_IDD is fatal.
_EXTRACTED = "extracted"
_INVALID_COUNTRY_CODE = "invalid_country_code"
_TOO_SHORT_AFTER_IDD = "too_short_after_idd"


def _maybe_extract_country_code(number: str, meta: dict | None) -> tuple[str, int, str]:
    """maybeExtractCountryCode, as (outcome, country code, national number).

    A number carrying its own calling code, whether by a plus or by the region's
    international dialling prefix, must resolve that code or fail. A number that
    does not is left to the default region, whose own calling code is stripped
    only when doing so turns an impossible number into a possible one.
    """
    idd = meta["international_prefix"] if meta else ""
    source, normalized = strip_international_prefix(number, idd)
    if source != FROM_DEFAULT_COUNTRY:
        if len(normalized) <= MIN_LENGTH_FOR_NSN:
            return _TOO_SHORT_AFTER_IDD, 0, ""
        code, national = extract_country_code(normalized)
        if code == 0:
            return _INVALID_COUNTRY_CODE, 0, ""
        return _EXTRACTED, code, national

    # The default branch reports a code only when it actually strips one, and
    # returns 0 otherwise. That distinction is what makes the retry work: on the
    # retry a 0 is fatal, while on the first pass the caller falls back to the
    # region's own calling code.
    if meta is not None:
        prefix = str(meta["country_code"])
        if normalized.startswith(prefix):
            candidate = _strip_national_prefix(normalized[len(prefix) :], meta)
            improved = not _match_national_number(normalized, meta) and _match_national_number(
                candidate, meta
            )
            if improved or _test_number_length(normalized, meta) == TOO_LONG:
                return _EXTRACTED, meta["country_code"], candidate
    return _EXTRACTED, 0, normalized


def _parse_national_number(value: str, region: str) -> tuple[int, str] | None:
    """parseHelper, returning (country code, national significant number)."""
    if utf16_length(value) > MAX_INPUT_STRING_LENGTH:
        return None
    number = build_national_number_for_parsing(value)
    if not is_viable_phone_number(number):
        return None
    meta = _region_meta(region)
    if meta is None and not starts_with_plus(number):
        # checkRegionForParsing: without a supported default region, only a number
        # carrying its own plus can be parsed.
        return None
    number = strip_extension(number)

    region_meta = meta
    outcome, code, national = _maybe_extract_country_code(number, region_meta)
    if outcome is _INVALID_COUNTRY_CODE and starts_with_plus(number):
        # parseHelper catches exactly this failure and tries again with the plus
        # removed, which lets the region's dialling prefix have a go at the
        # digits: under -c US, "+011 44 20 7946 0958" is a GB number reached
        # through the US IDD. A retry that still finds no code is fatal.
        plus = plus_prefix_length(number)
        outcome, code, national = _maybe_extract_country_code(number[plus:], region_meta)
        if outcome is not _EXTRACTED or code == 0:
            return None
    if outcome is not _EXTRACTED:
        return None
    if code == 0:
        # No code came out of the number itself, so the default region supplies
        # one. Without a supported region there is none, and the number fails.
        if region_meta is None:
            return None
        code = region_meta["country_code"]
    # parseHelper swaps in the resolved code's metadata only when that code
    # belongs to a different region than the one the caller supplied, so a
    # national number under -c US keeps the US metadata it was parsed with.
    resolved_region = tables()["code_regions"].get(str(code))
    meta = region_meta if resolved_region == region else _metadata_for_country_code(code)

    if len(national) < MIN_LENGTH_FOR_NSN:
        return None
    if meta is not None:
        candidate = _strip_national_prefix(national, meta)
        if _test_number_length(candidate, meta) not in (
            TOO_SHORT,
            IS_POSSIBLE_LOCAL_ONLY,
            INVALID_LENGTH,
        ):
            national = candidate
    if not (MIN_LENGTH_FOR_NSN <= len(national) <= MAX_LENGTH_FOR_NSN):
        return None
    return code, national


def is_possible_phone_number(value: str, region: str) -> bool:
    """Mirror DefaultFieldValidator.validatePhoneNumber's acceptance test.

    An unknown country skips validation entirely, so the notice cannot fire.
    Upstream tests CountryCode.isUnknown, and CountryCode accepts exactly
    Locale.getISOCountries() plus the ZZ sentinel, so "QQ" and "ZZ" skip while a
    real ISO country with no phone metadata ("AQ") is validated and fails.
    """
    if not region:
        return True
    region = region.upper()
    if region == UNKNOWN_COUNTRY or region not in iso_countries():
        return True

    parsed = _parse_national_number(value, region)
    if parsed is None:
        return False
    code, national = parsed
    meta = _metadata_for_country_code(code)
    if meta is None:
        lengths = tables()["calling_codes"].get(str(code))
        return lengths is not None and len(national) in lengths
    return _test_number_length(national, meta) in (IS_POSSIBLE, IS_POSSIBLE_LOCAL_ONLY)
