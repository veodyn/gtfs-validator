"""The email port is tested against measured commons-validator behaviour.

See tests/test_urls.py for why the oracle exists and how it is produced.
"""

import json
from pathlib import Path

import pytest

from gtfs_validator.fieldtypes.emails import is_valid_email

ORACLE = json.loads((Path(__file__).parent / "data" / "validator_oracle.json").read_text())["email"]


@pytest.mark.parametrize(("value", "expected"), sorted(ORACLE.items()))
def test_matches_commons_validator(value, expected):
    assert is_valid_email(value) is expected


def test_the_oracle_is_not_trivially_one_sided():
    assert set(ORACLE.values()) == {True, False}
    assert len(ORACLE) > 25


def test_the_surprising_cases():
    # Surrounding whitespace is trimmed by the top-level pattern, not rejected.
    assert is_valid_email(" someone@example.com ")
    # A bare TLD is not a domain, and localhost has no TLD at all.
    assert not is_valid_email("someone@com")
    assert not is_valid_email("someone@localhost")
    # Greedy local part means the first @ is not the separator.
    assert not is_valid_email("two@at@example.com")


def test_java_whitespace_is_ascii_only():
    # EMAIL_REGEX trims with \s, and the local-part charset excludes \s, both
    # ASCII-only in Java. A non-breaking space is therefore an ordinary local-part
    # character, and it is not trimmed from the end.
    assert is_valid_email("us\xa0er@example.com")
    assert not is_valid_email("someone@example.com\xa0")
    assert is_valid_email("someone@example.com ")
    assert not is_valid_email("us er@example.com")
