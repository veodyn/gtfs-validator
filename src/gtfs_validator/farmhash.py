"""Guava's `Hashing.farmHashFingerprint64`, because a notice order depends on it.

`StopTimeTravelSpeedValidator` groups trips by a 64-bit fingerprint of the trip's route and
its stop pattern, and then iterates `Multimaps.asMap(tripsByHash)`. The multimap is keyed by
that fingerprint as a `Long`, so the bucket a group lands in, and therefore the order the
notices come out in, is decided by the hash value itself. Grouping trips by an equal-tuple
test reproduces *which* trips share a group; only the hash reproduces the order they are
reported in, which is what decides the surviving 1,000 above the sample cap.

The algorithm is FarmHash's `Fingerprint64`, seedless, in the four length classes Guava
splits it into. It is transcribed rather than derived, and checked against the Guava bundled
in the pinned jar by `tools/diff_farmhash_against_guava.py` over a generated corpus that
crosses every one of those class boundaries.

`hasher()` is the second half and is just as much of a contract: Guava's fingerprint function
is non-streaming, so its `Hasher` buffers every byte and hashes once at the end. `putInt`
writes four bytes little-endian and `putUnencodedChars` writes each UTF-16 code unit as two
bytes little-endian, which is *not* UTF-8: a two-character id is four bytes here whatever its
characters are, and a non-BMP character contributes its two surrogates.
"""

from __future__ import annotations

import struct

_MASK = 0xFFFFFFFFFFFFFFFF
_SIGN_BIT = 0x8000000000000000

K0 = 0xC3A5C85C97CB3127
K1 = 0xB492B66FBE98F273
K2 = 0x9AE16A3B2F90404F
# hashLength65Plus starts from this rather than taking a seed: Fingerprint64 is seedless.
_SEED = 81


def _rotate_right(value: int, bits: int) -> int:
    """`Long.rotateRight`, which for bits == 0 must not shift by 64."""
    bits &= 63
    if bits == 0:
        return value
    return ((value >> bits) | (value << (64 - bits))) & _MASK


def _shift_mix(value: int) -> int:
    return value ^ (value >> 47)


def _load64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _load32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _hash_length_16(first: int, second: int, multiplier: int) -> int:
    value = ((first ^ second) * multiplier) & _MASK
    value ^= value >> 47
    result = ((second ^ value) * multiplier) & _MASK
    result ^= result >> 47
    return (result * multiplier) & _MASK


def _hash_length_0_to_16(data: bytes) -> int:
    length = len(data)
    if length >= 8:
        multiplier = (K2 + length * 2) & _MASK
        first = (_load64(data, 0) + K2) & _MASK
        second = _load64(data, length - 8)
        third = (_rotate_right(second, 37) * multiplier + first) & _MASK
        fourth = ((_rotate_right(first, 25) + second) * multiplier) & _MASK
        return _hash_length_16(third, fourth, multiplier)
    if length >= 4:
        multiplier = (K2 + length * 2) & _MASK
        first = _load32(data, 0)
        return _hash_length_16(
            (length + (first << 3)) & _MASK, _load32(data, length - 4), multiplier
        )
    if length > 0:
        first = data[0]
        middle = data[length >> 1]
        last = data[length - 1]
        # Java widens these to int before multiplying, so the products are taken mod 2**64
        # only at the end; both operands are small enough that it makes no difference.
        mixed = (first + (middle << 8)) * K2 ^ (length + (last << 2)) * K0
        return (_shift_mix(mixed & _MASK) * K2) & _MASK
    return K2


def _hash_length_17_to_32(data: bytes) -> int:
    length = len(data)
    multiplier = (K2 + length * 2) & _MASK
    first = (_load64(data, 0) * K1) & _MASK
    second = _load64(data, 8)
    third = (_load64(data, length - 8) * multiplier) & _MASK
    fourth = (_load64(data, length - 16) * K2) & _MASK
    return _hash_length_16(
        (_rotate_right((first + second) & _MASK, 43) + _rotate_right(third, 30) + fourth) & _MASK,
        (first + _rotate_right((second + K2) & _MASK, 18) + third) & _MASK,
        multiplier,
    )


def _hash_length_33_to_64(data: bytes) -> int:
    length = len(data)
    multiplier = (K2 + length * 2) & _MASK
    first = (_load64(data, 0) * K2) & _MASK
    second = _load64(data, 8)
    third = (_load64(data, length - 8) * multiplier) & _MASK
    fourth = (_load64(data, length - 16) * K2) & _MASK
    y = (_rotate_right((first + second) & _MASK, 43) + _rotate_right(third, 30) + fourth) & _MASK
    z = _hash_length_16(
        y, (first + _rotate_right((second + K2) & _MASK, 18) + third) & _MASK, multiplier
    )
    e = (_load64(data, 16) * multiplier) & _MASK
    f = _load64(data, 24)
    g = ((y + _load64(data, length - 32)) * multiplier) & _MASK
    # `length - 24`, and the earlier `d` above reads `length - 16`. Reading the same offset
    # twice is the transcription slip this file made first, and it cost every input of 33 to
    # 64 bytes while nothing shorter or longer moved. Guava is not unusual here: the published
    # FarmHash reads `len - 24` for `h` too (`farmhashna::HashLen33to64`, which is what
    # `Fingerprint64` dispatches to), so this is a port bug that was fixed, not a divergence.
    h = ((z + _load64(data, length - 24)) * multiplier) & _MASK
    return _hash_length_16(
        (_rotate_right((e + f) & _MASK, 43) + _rotate_right(g, 30) + h) & _MASK,
        (e + _rotate_right((f + first) & _MASK, 18) + g) & _MASK,
        multiplier,
    )


def _weak_hash_length_32(data: bytes, offset: int, seed_a: int, seed_b: int) -> tuple[int, int]:
    part1 = _load64(data, offset)
    part2 = _load64(data, offset + 8)
    part3 = _load64(data, offset + 16)
    part4 = _load64(data, offset + 24)

    seed_a = (seed_a + part1) & _MASK
    seed_b = _rotate_right((seed_b + seed_a + part4) & _MASK, 21)
    carried = seed_a
    seed_a = (seed_a + part2 + part3) & _MASK
    seed_b = (seed_b + _rotate_right(seed_a, 44)) & _MASK
    return (seed_a + part4) & _MASK, (seed_b + carried) & _MASK


def _hash_length_65_plus(data: bytes) -> int:
    length = len(data)
    x = _SEED
    y = (_SEED * K1 + 113) & _MASK
    z = (_shift_mix((y * K2 + 113) & _MASK) * K2) & _MASK
    v = (0, 0)
    w = (0, 0)
    x = (x * K2 + _load64(data, 0)) & _MASK

    offset = 0
    # Leaves between 1 and 64 bytes for the tail, which is re-read from `last64` below and so
    # overlaps what the loop already consumed whenever the length is not a multiple of 64.
    end = ((length - 1) // 64) * 64
    last64 = end + ((length - 1) & 63) - 63
    while True:
        x = (_rotate_right((x + y + v[0] + _load64(data, offset + 8)) & _MASK, 37) * K1) & _MASK
        y = (_rotate_right((y + v[1] + _load64(data, offset + 48)) & _MASK, 42) * K1) & _MASK
        x ^= w[1]
        y = (y + v[0] + _load64(data, offset + 40)) & _MASK
        z = (_rotate_right((z + w[0]) & _MASK, 33) * K1) & _MASK
        v = _weak_hash_length_32(data, offset, (v[1] * K1) & _MASK, (x + w[0]) & _MASK)
        w = _weak_hash_length_32(
            data, offset + 32, (z + w[1]) & _MASK, (y + _load64(data, offset + 16)) & _MASK
        )
        x, z = z, x
        offset += 64
        if offset == end:
            break

    multiplier = (K1 + ((z & 0xFF) << 1)) & _MASK
    offset = last64
    w = ((w[0] + ((length - 1) & 63)) & _MASK, w[1])
    v = ((v[0] + w[0]) & _MASK, v[1])
    w = ((w[0] + v[0]) & _MASK, w[1])

    x = (_rotate_right((x + y + v[0] + _load64(data, offset + 8)) & _MASK, 37) * multiplier) & _MASK
    y = (_rotate_right((y + v[1] + _load64(data, offset + 48)) & _MASK, 42) * multiplier) & _MASK
    x ^= (w[1] * 9) & _MASK
    y = (y + v[0] * 9 + _load64(data, offset + 40)) & _MASK
    z = (_rotate_right((z + w[0]) & _MASK, 33) * multiplier) & _MASK
    v = _weak_hash_length_32(data, offset, (v[1] * multiplier) & _MASK, (x + w[0]) & _MASK)
    w = _weak_hash_length_32(
        data, offset + 32, (z + w[1]) & _MASK, (y + _load64(data, offset + 16)) & _MASK
    )
    return _hash_length_16(
        (_hash_length_16(v[0], w[0], multiplier) + (_shift_mix(y) * K0) + x) & _MASK,
        (_hash_length_16(v[1], w[1], multiplier) + z) & _MASK,
        multiplier,
    )


def fingerprint64(data: bytes) -> int:
    """The fingerprint as a **signed** 64-bit int, which is how Java holds and keys it."""
    length = len(data)
    if length <= 16:
        value = _hash_length_0_to_16(data)
    elif length <= 32:
        value = _hash_length_17_to_32(data)
    elif length <= 64:
        value = _hash_length_33_to_64(data)
    else:
        value = _hash_length_65_plus(data)
    return value - (_MASK + 1) if value & _SIGN_BIT else value


class Hasher:
    """The buffering `Hasher` a non-streaming Guava hash function hands out.

    Only the `put` methods upstream calls are here. Adding one that is never used would
    be a claim about Guava that nothing in this project checks.
    """

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def put_int(self, value: int) -> Hasher:
        self._parts.append(struct.pack("<i", value))
        return self

    def put_double(self, value: float) -> Hasher:
        """`putDouble`, which is `putLong(doubleToRawLongBits(d))`: eight little-endian bytes.

        Raw bits, so -0.0 and 0.0 hash differently even though they compare equal, and a NaN
        hashes as whatever payload it carries. `ShapeToStopMatchingValidator` feeds this a
        `shape_dist_traveled`, where an unset value arrives as a plain 0.0.
        """
        self._parts.append(struct.pack("<d", value))
        return self

    def put_unencoded_chars(self, value: str) -> Hasher:
        """Each UTF-16 code unit as two little-endian bytes, surrogates included."""
        self._parts.append(value.encode("utf-16-le"))
        return self

    def hash(self) -> int:
        return fingerprint64(b"".join(self._parts))
