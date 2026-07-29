"""The corpora `diff_hashmap_against_jdk.py` compares against the JDK.

Split out from the tool when the two together passed the 300-line limit. The division is by
what each half is for rather than by size: this file decides *what shapes get tested*, and
the tool next door decides how to ask Java and how to report a disagreement. The shapes are
the part worth reading on their own, since every one of them exists because some threshold in
`HashMap` is reachable and a corpus assembled from what comes to mind would not reach it.

Every case is generated to cross a threshold the implementation must know about, whether or
not it currently does: the 0.75 resize, the 8-entry treeify threshold, the 64-entry minimum
capacity that gates it, and the 6-entry untreeify threshold a resize can drop a bin through.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gtfs_validator.javahash import long_hash, spread, string_hash

# "Aa" and "BB" hash identically, so any concatenation of them does too. Ten positions
# give 1,024 distinct keys sharing one hashCode, which is one bucket at any capacity.
_COLLIDING_PAIR = ("Aa", "BB")


def colliding_keys(count: int, width: int = 10) -> list[str]:
    """`count` distinct keys that all share a single `hashCode`."""
    keys = []
    for index in range(count):
        bits = format(index, f"0{width}b")
        keys.append("".join(_COLLIDING_PAIR[int(bit)] for bit in bits))
    return keys


def same_bucket_keys(count: int, bits: int = 6) -> list[str]:
    """`count` keys agreeing in the low `bits` of their spread hash and nowhere above it.

    Distinct hashes, one bucket while the table is small, two once it grows past `bits`.
    """
    found: dict[int, list[str]] = {}
    index = 0
    while True:
        key = f"k{index}"
        bucket = spread(string_hash(key)) & ((1 << bits) - 1)
        found.setdefault(bucket, []).append(key)
        if len(found[bucket]) == count:
            return found[bucket]
        index += 1


def string_corpora() -> dict[str, list[str]]:
    """Every case for the string-keyed tables, which is both `hashmap` and `multimap`."""
    cases: dict[str, list[str]] = {}

    # Ordinary keys, spanning several resizes. These already passed before treeification
    # was modelled, and are kept so a treeification fix cannot regress them.
    #
    # The small sizes carry more weight than they look. A plain HashMap starts at 16 buckets and
    # a Guava multimap at 32, so the two disagree only until enough insertions bring them to the
    # same capacity. Every size below about 25 is where that difference is visible, and the
    # original corpus went 1, 2, 12, 13, 49 and then straight to the thousands, which is how a
    # wrong initial capacity survived it.
    for size in (*range(1, 27), 30, 40, 49, 100, 1005, 2000):
        cases[f"sequential-{size}"] = [f"T{index:04d}" for index in range(size)]
    # Sequential ids share a prefix and land in a narrow band of buckets. These do not.
    for size in (5, 6, 7, 8, 11, 17, 23, 25):
        cases[f"scattered-{size}"] = [f"S{index + 6}" for index in range(size)]

    # Seeded, because a corpus that changes run to run cannot be cited in a commit.
    rng = random.Random(20260725)  # noqa: S311 - corpus generation, not cryptography
    for size in (17, 200, 1500):
        generated = [
            "".join(
                rng.choice("abcdefghijklmnopqrstuvwxyz0123456789_-")
                for _ in range(rng.randint(1, 12))
            )
            for _ in range(size)
        ]
        # A generator can repeat; HashMap would collapse the repeat and hashmap_order
        # documents that its input must not.
        cases[f"random-{size}"] = list(dict.fromkeys(generated))

    # One bucket, every depth around the treeify threshold. Treeification needs capacity
    # >= 64, and a bin that deep in a small table forces a resize instead, so with nothing
    # but colliding keys the first tree appears later than the threshold alone suggests.
    for size in (2, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 40, 48, 49, 64, 100, 500, 1024):
        cases[f"colliding-{size}"] = colliding_keys(size)

    # Reversed and shuffled insertion, because a tree's root depends on insertion order
    # while a list's order is insertion itself.
    cases["colliding-100-reversed"] = list(reversed(colliding_keys(100)))
    shuffled = colliding_keys(100)
    random.Random(7).shuffle(shuffled)  # noqa: S311
    cases["colliding-100-shuffled"] = shuffled

    # A deep bin plus enough ordinary keys to force resizes past it, exercising the
    # treeified split and the untreeify that follows a split small enough.
    for depth in (7, 8, 9, 10, 11, 12, 30):
        for filler in (0, 40, 60, 100, 200):
            keys = colliding_keys(depth) + [f"F{index:04d}" for index in range(filler)]
            cases[f"deep-{depth}-filler-{filler}"] = keys
            cases[f"filler-{filler}-deep-{depth}"] = list(reversed(keys))

    # Keys that share a bucket at capacity 16 but separate later, so a split moves them
    # apart without any tree involved.
    cases["bucket-16-siblings"] = [f"{'x' * index}-{index}" for index in range(30)]

    # A bin deep enough to treeify whose keys have *different* hashes agreeing only in the
    # low bits, so the next resize splits it into two non-empty halves. That is the branch
    # where a bin either rebuilds its tree or drops back to a list, and one whose keys all
    # share a single hash can never reach it: they always move together.
    for depth in (8, 10, 14, 20):
        for filler in (60, 200):
            keys = same_bucket_keys(depth) + [f"G{index:04d}" for index in range(filler)]
            cases[f"splitting-{depth}-filler-{filler}"] = keys

    # Non-BMP and non-ASCII keys, since hashCode runs over UTF-16 units. This is the
    # distinction that has produced five separate defects in this project.
    cases["astral"] = [f"\U0001f600{index}é" for index in range(50)]
    cases["astral-colliding"] = [key + "\U0001f600" for key in colliding_keys(20)]

    # Empty string is a legal GTFS id in the tables that do not require one.
    cases["with-empty"] = [""] + [f"S{index}" for index in range(20)]

    return cases


def long_corpora() -> dict[str, list[int]]:
    """Corpora for the `Long`-keyed table, built to reach the cases strings cannot.

    Trip fingerprints are 64-bit and effectively random, so an ordinary corpus never puts nine
    of them in one bucket. Colliding ones are easy to construct on purpose: `Long.hashCode` is
    the two halves folded with xor, so holding that fold constant while varying the high half
    gives as many distinct keys in one bucket as wanted. Depths either side of the treeify
    threshold are the point, because that is where the tree decides the order.

    Two things here that strings cannot reach at all: a key whose *sign* the tree's `compareTo`
    has to respect, and a *hash code* whose sign the fold in `spread` has to respect.
    `String.hashCode` can be negative, but `spread` only ever saw the value `string_hash`
    returns, which this project holds unsigned.
    """
    cases: dict[str, list[int]] = {}
    rng = random.Random(20260726)  # noqa: S311 - corpus generation, not cryptography
    for size in (1, 5, 17, 200, 1500):
        cases[f"random-{size}"] = list(
            dict.fromkeys(rng.randrange(-(2**63), 2**63) for _ in range(size))
        )
    for size in (2, 8, 9, 10, 11, 12, 16, 64, 100, 500):
        cases[f"colliding-{size}"] = colliding_longs(size)
    cases["colliding-100-reversed"] = list(reversed(colliding_longs(100)))
    shuffled = colliding_longs(100)
    random.Random(8).shuffle(shuffled)  # noqa: S311
    cases["colliding-100-shuffled"] = shuffled
    # A negative *hash code*, which `fold=-7` gives while leaving every key positive.
    cases["colliding-negative-hash"] = colliding_longs(20, fold=-7)
    # Negative and positive *keys* in one deep bin. The tree falls back to `compareTo` once the
    # hashes tie, and `Long.compareTo` is signed: a port comparing the unsigned 64-bit values
    # puts these in the opposite order. The first version of this corpus meant to cover that
    # and did not, because `fold=-7` moves the sign of the hash and not of the key.
    for size in (12, 20):
        cases[f"colliding-signed-keys-{size}"] = colliding_longs(size, signed=True)
    # Differing hashes of *both* signs in one treeified bin. A tree orders by hash before it
    # ever reaches the key, so this is the only shape that can see the fold in `spread`, and
    # `colliding-*` cannot: keys sharing one hash compare equal at that step whatever the fold
    # does to it. The bin's membership is not at risk either way, since the low bits the bucket
    # index reads come out the same under an arithmetic shift and an unsigned one.
    for depth in (9, 12):
        cases[f"mixed-sign-hashes-{depth}"] = mixed_sign_hash_bin(depth)
    for depth in (9, 12):
        for filler in (0, 60, 200):
            keys = colliding_longs(depth) + [10_000 + index for index in range(filler)]
            cases[f"deep-{depth}-filler-{filler}"] = keys
    return cases


def colliding_longs(count: int, fold: int = 12345, signed: bool = False) -> list[int]:
    """`count` distinct longs sharing one `Long.hashCode`, hence one bucket at any capacity.

    `signed` sets the top bit of every other key's high half, which makes the key negative
    without touching its hash: the fold is `high ^ low`, and `low` is derived from `high`.
    """
    keys = []
    for index in range(1, count + 1):
        high = index | 0x80000000 if signed and index % 2 else index
        low = (fold ^ high) & 0xFFFFFFFF
        value = (high << 32) | low
        keys.append(value - (1 << 64) if value & (1 << 63) else value)
    if len({long_hash(key) for key in keys}) != 1:
        raise SystemExit("the colliding-long corpus does not collide")
    if signed and not min(keys) < 0 < max(keys):
        raise SystemExit("the signed-long corpus holds keys of one sign only")
    return keys


def mixed_sign_hash_bin(depth: int, filler: int = 30) -> list[int]:
    """`depth` keys in one bin at capacity 64, their hash codes distinct and of both signs.

    The filler comes first and is there only to grow the table: treeification needs 64 buckets,
    and a multimap reaches those at 25 entries. Small enough overall that the next resize never
    arrives, so the bin is still a tree when the order is read.
    """
    keys = [10_000_000 + index for index in range(filler)]
    bucket = spread(long_hash(keys[0])) & 63
    rng = random.Random(20260727)  # noqa: S311 - corpus generation, not cryptography
    # Both signs present in numbers, so neither the ordering of two negatives nor that of a
    # negative against a positive is left to one accident of the draw.
    wanted = {True: depth // 2, False: depth - depth // 2}
    chosen: dict[bool, list[int]] = {True: [], False: []}
    codes: set[int] = set()
    while len(chosen[True]) + len(chosen[False]) < depth:
        candidate = rng.randrange(-(2**63), 2**63)
        code = long_hash(candidate)
        if spread(code) & 63 != bucket or code in codes:
            continue
        half = chosen[code < 0]
        if len(half) >= wanted[code < 0]:
            continue
        codes.add(code)
        half.append(candidate)
    if not chosen[True] or not chosen[False]:
        raise SystemExit("the mixed-sign-hash corpus reached one sign only")
    return keys + chosen[True] + chosen[False]
