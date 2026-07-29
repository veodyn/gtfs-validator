"""`gtfs_validator.farmhash` against values taken from the Guava in the pinned jar.

The generated corpus lives in `tools/diff_farmhash_against_guava.py`, which needs java. These
are a handful of its cases pinned so the suite covers the port on a machine without one, one
per length class and one either side of each boundary the implementation branches on.
"""

from __future__ import annotations

import pytest

from gtfs_validator.farmhash import Hasher, fingerprint64
from gtfs_validator.rules._shared.travel_speed import trip_fingerprint

# (input bytes as hex, the signed long Guava returns). Measured by tools/_oracle/DumpFarmHash.
# One per length class and one either side of each boundary, which means the long path as well:
# a review found the first version of this list stopping at 33 bytes, where a wholly wrong
# `_hash_length_65_plus` would still have passed. A second review found the same gap at the
# other end. `_hash_length_0_to_16` is four branches, not one, and the list ran 0, 8, 16, which
# left the 1-to-3 and 4-to-7 paths resting on the tool alone. Lengths 1 through 7 are all here
# now: those two branches read the first, middle and last byte by index, so an off-by-one in
# any of them survives a corpus that skips the lengths where the three coincide.
VECTORS = [
    ("", -7286425919675154353),
    ("61", -5528939962900187677),
    ("6263", 6006289270716924279),
    ("313233", -3222588021317909685),
    ("41424344", 6056751185092765998),
    ("4142434445", 810150157697533163),
    ("7f8081828384", -2895048782566701537),
    ("01020304050607", -595729442367573010),
    ("0102030405060708090a0b0c0d0e", 6872298837149963838),
    ("fee9232f8af2211f", 146255703028567809),
    ("63b0e4b2ba29703474f064ac68f700f5", 3348437755758341080),
    ("e15d024c5848f23d1fa6f7361d7f618d15", 2204010299145672789),
    ("fef8c90c5101fbe6cf9a48d5b0c0a13da900a6adcb3d64069481be21c9c727b8", -6903297992953645175),
    ("7f37724f4d37ea2b14004077139b4180df3932249962c6857200059aeb8ea17cf3", 2620398040735917086),
    (
        (
            "69683911112c93f43343326896a3acd8850ab3839018bca4f3930fd30fdf32b1"
            "f0186e2e9357df0067931b02b2fb30fb5efdb18551916d76ff543829fb35a7b6"
        ),
        -3056234555534313866,
    ),
    (
        (
            "e7b14e6ace552e9865fd6d28e03b3c87d67747f2fc1df7ef49fb7eff540352a4"
            "effe97eebfdad6265cb80e0a17a930f7f849116dd440ad30bbaef26b91deafd880"
        ),
        -343744065698145552,
    ),
    (
        (
            "7b76b568a6d98e98ff6e50f4884599902da902f87f52a3e76c1a6bb817e05dde"
            "47980c394d04449a4db43156edcb2ed4adcbab10786707134576dc350a18a2213"
            "83df945db015b724b39b5fe27b26e72258b5a07878923166418d0b98805a615e"
            "890a9d289ccd8a2d6c44dc6c5d149027a82c17b653b2c1119cfa6e2a1e900f2"
        ),
        7493892333241835720,
    ),
]


@pytest.mark.parametrize(("data", "expected"), VECTORS)
def test_the_fingerprint_matches_guava(data, expected):
    assert fingerprint64(bytes.fromhex(data)) == expected


def test_an_empty_input_is_the_third_constant():
    """The 0-byte case returns K2 itself, which is negative as a signed long."""
    assert fingerprint64(b"") == -7286425919675154353


def test_the_hasher_writes_little_endian_ints_and_utf16_chars():
    """Guava's `putInt` is four bytes little-endian and `putUnencodedChars` is UTF-16LE.

    Not UTF-8: `é` is one code unit and two bytes here, and would be two bytes of UTF-8 with a
    different pair of values. Checking the assembled stream against `fingerprint64` of the
    bytes spelled out is what pins the encoding rather than the hash.
    """
    hasher = Hasher()
    hasher.put_int(1).put_unencoded_chars("é")
    assert hasher.hash() == fingerprint64(b"\x01\x00\x00\x00\xe9\x00")


def test_a_non_bmp_id_counts_two_code_units():
    """`String.length()` is code units, so an emoji id hashes as length 2.

    The fingerprint disagreed with Guava on every trip holding one until this was fixed, and
    the two spellings differ only in the integer written before the characters.
    """
    rows = [{"stop_id": "🚉", "arrival_time": 0, "departure_time": 0}]
    hasher = Hasher()
    hasher.put_int(0).put_unencoded_chars("").put_int(1)
    hasher.put_int(2).put_unencoded_chars("🚉").put_int(0).put_int(0)
    assert trip_fingerprint("", rows) == hasher.hash()
