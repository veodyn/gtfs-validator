"""The URL port is tested against measured commons-validator behaviour.

tests/data/validator_oracle.json records what the real
UrlValidator.getInstance().isValid says for every case, produced by
tools/build_validator_oracle.py running against the bundled implementation in
the pinned jar. Asserting against that rather than against intuition is the
whole point: this is the port the spec calls the riskiest in the project.
"""

import json
from pathlib import Path

import pytest

from gtfs_validator.fieldtypes.urls import is_valid_url

ORACLE = json.loads((Path(__file__).parent / "data" / "validator_oracle.json").read_text())["url"]


@pytest.mark.parametrize(("value", "expected"), sorted(ORACLE.items()))
def test_matches_commons_validator(value, expected):
    assert is_valid_url(value) is expected


def test_the_oracle_is_not_trivially_one_sided():
    # Guards against a fixture that regenerated into all-True or all-False and
    # would then pass against any implementation at all.
    verdicts = set(ORACLE.values())
    assert verdicts == {True, False}
    assert len(ORACLE) > 40


def test_the_quirks_that_motivate_the_port():
    # urllib.parse and a naive regex both get these wrong in the other direction.
    assert not is_valid_url("http://localhost")  # no TLD
    assert not is_valid_url("http://example.com//double")  # ALLOW_2_SLASHES off
    assert not is_valid_url("mailto:someone@example.com")  # scheme not allowed
    assert not is_valid_url("http://example.transit")  # TLD not in the 2017 table
    assert is_valid_url("http://example.xyz")  # but this one is


def test_userinfo_is_validated_not_just_stripped():
    # commons applies a userinfo grammar; it does not accept anything before @.
    assert is_valid_url("http://user:pass@example.com/")
    assert is_valid_url("http://user@example.com/")
    assert not is_valid_url("http://user name@example.com/")  # space forbidden
    assert not is_valid_url("http://us|er@example.com/")  # pipe forbidden
    assert not is_valid_url("http://a@b@example.com/")  # second @ stays in host
    assert not is_valid_url("http://@example.com/")  # empty userinfo needs a char


def test_bracketed_ipv6_follows_the_commons_charset_not_ipaddress():
    # The bracketed branch is [0-9a-fA-F:]+, so a scope id and the dotted
    # IPv4-mapped form are rejected even though ipaddress parses both.
    assert is_valid_url("http://[::1]/")
    assert is_valid_url("http://[1:2:3:4:5:6:7:8]/")
    assert not is_valid_url("http://[fe80::1%eth0]/")
    assert not is_valid_url("http://[::ffff:192.0.2.1]/")
    assert not is_valid_url("http://[gggg::1]/")  # charset ok, address is not
    assert not is_valid_url("http://[]/")


def test_port_range_is_checked_on_the_domain_branch_only():
    # A commons quirk, measured: the bracketed branch never range-checks its port.
    assert not is_valid_url("http://example.com:65536")
    assert is_valid_url("http://example.com:65535")
    assert is_valid_url("http://[::1]:99999")
    assert not is_valid_url("http://[::1]:port")


def test_the_whole_authority_is_idn_normalised_not_just_the_host():
    # commons runs unicodeToASCII over the entire authority before splitting it,
    # so the punycode of a non-ASCII label absorbs a ":" or "@" that follows it.
    assert is_valid_url("https://\u4f8b\u5b50.\u4e2d\u56fd/path")
    assert not is_valid_url("http://\u4f8b\u5b50.\u4e2d\u56fd:80/")  # the port is eaten
    assert not is_valid_url("http://user@\u4f8b\u5b50.\u4e2d\u56fd/")  # so is the "@"
    # An all-ASCII label is passed through untouched, so these keep both.
    assert is_valid_url("https://m\u00fcnchen.de:8080/")
    assert is_valid_url("http://user@m\u00fcnchen.de/")


def test_a_code_point_unassigned_in_unicode_3_2_is_rejected():
    # Java's nameprep prohibits RFC 3454 table A.1; Python's does not check it, so
    # this host punycodes cleanly in Python and throws in Java. commons keeps the
    # unconverted input, which then fails the ASCII-only authority charset.
    assert not is_valid_url("http://a\U0001f984b.com/")
    assert is_valid_url("http://m\u00fcnchen.de/")


def test_a_punycoded_tld_is_not_a_special_case():
    # TOP_LABEL_REGEX is one alpha then alphanumerics and hyphens, with no "xn--"
    # branch at all. Two vendored TLDs carry an internal hyphen, so spelling the
    # ACE form as "xn--" plus alphanumerics rejects a domain upstream accepts.
    assert is_valid_url("http://example.xn--vermgensberater-ctb")
    assert is_valid_url("http://example.vermögensberater")
    assert is_valid_url("http://example.xn--fiqs8s")


def test_the_ipv6_branch_shares_the_port_and_extra_groups():
    # The port and the trailing "extra" sit outside the alternation in commons'
    # AUTHORITY_REGEX, so a bracketed host tolerates trailing whitespace exactly
    # as a domain does. Splitting the branches by hand loses that.
    assert is_valid_url("http://[::1]:80   /")
    assert is_valid_url("http://[::1]:80 ")
    assert is_valid_url("http://[::1]   /")
    assert is_valid_url("http://example.com:80   /")


def test_java_character_classes_are_ascii_only():
    # commons sets UNICODE_CHARACTER_CLASS nowhere, so \w in PATH_REGEX is
    # [a-zA-Z_0-9] and \s in QUERY_REGEX is ASCII whitespace. Transliterating them
    # into Python without re.ASCII widens the first and narrows the second.
    assert not is_valid_url("http://example.com/café")
    assert not is_valid_url("http://example.com/日本")
    assert not is_valid_url("http://example.com/\u0660")
    assert is_valid_url("http://example.com/cafe")
    # A non-breaking space is not whitespace to Java, so the query accepts it.
    assert is_valid_url("http://example.com/?a=\xa0b")
    assert not is_valid_url("http://example.com/?a= b")


def test_a_supplementary_digit_is_not_a_port():
    # U+104A1 is \p{Nd} but not [0-9], and IDN conversion rejects it as unassigned
    # in Unicode 3.2, so it survives into the authority. Python's Unicode-aware \d
    # read it as a port, and the IPv6 branch does not range-check ports.
    assert not is_valid_url("http://[::1]:\U000104a1/")
    assert not is_valid_url("http://[::1]:1\U000104a1/")
    assert is_valid_url("http://[::1]:80/")
