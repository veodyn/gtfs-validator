"""HashMap iteration order, including the treeified bins that reorder it.

Every expectation here was measured on the pinned jar by tools/diff_hashmap_against_jdk.py,
which compares 146 generated corpora against both `java.util.HashMap` and Guava's
`ArrayListMultimap`. These are the cases worth keeping in the suite so a change is caught without
a JVM on the machine: the boundary where a tree first appears, the two orders either side of it, a
tree that survives many resizes, a bin that splits into two non-empty halves, keys whose ordering
depends on UTF-16 comparison, and the small key counts where the two collections' initial
capacities still differ.
"""

from __future__ import annotations

from gtfs_validator.javahash import (
    auto_value_hash,
    grouping_by_order,
    hashmap_order,
    long_multimap_order,
    multimap_order,
    spread,
    string_hash,
)
from gtfs_validator.javatext import compare_to


# "Aa" and "BB" share a hashCode, so any concatenation of them does too.
def colliding(count: int, width: int = 10) -> list[str]:
    return [
        "".join(("Aa", "BB")[int(bit)] for bit in format(index, f"0{width}b"))
        for index in range(count)
    ]


def test_string_hash_counts_utf16_units():
    """An astral character hashes as its surrogate pair, not as one code point."""
    assert string_hash("Aa") == string_hash("BB") == 2112
    assert string_hash("\U0001f600") == string_hash("😀")


def test_spread_is_signed():
    """A treeified bin compares hashes with `<`, so the sign has to survive the fold.

    An unsigned fold diverges on 20 of the harness's 114 corpora, which are exactly the
    ones whose treeified bins hold hashes of both signs. Short keys do not reach the high
    bit at all, so a sample of them tests nothing.
    """
    assert spread(string_hash("stop_id_long_enough")) == -1292170313
    assert spread(string_hash("k101")) > 0


def test_a_bin_of_ten_equal_hashes_is_still_a_list():
    """Ten keys sharing one hashCode iterate in insertion order.

    `putVal` treeifies after walking eight nodes, so the bin holds nine by then, and
    `treeifyBin` under 64 buckets resizes instead. Two such resizes carry capacity from 16
    to 64, which is why ten is still a list.
    """
    keys = colliding(10)
    assert hashmap_order(keys) == keys


def test_the_eleventh_equal_hash_key_builds_the_tree():
    """The eleventh insertion finds capacity 64 and a bin of ten, and treeifies.

    The order then starts with the tree's root, which `moveRootToFront` lifts out of the
    middle of the list. Before treeification was modelled this returned insertion order.
    """
    order = hashmap_order(colliding(11))
    assert order[:4] == [
        "AaAaAaAaAaAaAaAaBBBB",
        "AaAaAaAaAaAaAaAaAaAa",
        "AaAaAaAaAaAaAaAaAaBB",
        "AaAaAaAaAaAaAaAaBBAa",
    ]
    assert order != colliding(11)


def test_a_tree_of_a_thousand_survives_every_resize():
    """1,024 keys sharing one hash never split, so no resize rebuilds the tree.

    This is the corpus that made the gap worth closing: it is above the 1,000-sample cap,
    so the order decides which notices a report keeps.
    """
    order = hashmap_order(colliding(1024))
    assert order[:6] == [
        "AaAaBBBBBBBBBBBBBBBB",
        "AaAaAaBBBBBBBBBBBBBB",
        "AaAaAaAaBBBBBBBBBBBB",
        "AaAaAaAaAaBBBBBBBBBB",
        "AaAaAaAaAaAaBBBBBBBB",
        "AaAaAaAaAaAaAaBBBBBB",
    ]
    assert len(order) == 1024


def test_a_split_bin_rebuilds_its_tree():
    """Keys agreeing only in the low six bits share a bin, then separate on resize.

    Both halves are non-empty, which is the one condition under which a half rebuilds its
    tree and moves a new root to the front. A bin of equal-hash keys never reaches it.
    """
    deep = [
        "k101",
        "k123",
        "k145",
        "k167",
        "k189",
        "k200",
        "k222",
        "k244",
        "k266",
        "k288",
        "k321",
        "k343",
        "k365",
        "k387",
    ]
    order = hashmap_order(deep + [f"G{index:04d}" for index in range(60)])
    assert [key for key in order if key.startswith("k")] == [
        "k222",
        "k101",
        "k145",
        "k189",
        "k266",
        "k343",
        "k387",
        "k244",
        "k167",
        "k123",
        "k200",
        "k288",
        "k321",
        "k365",
    ]


def test_a_tree_orders_astral_keys_by_utf16_units():
    """Equal-hash keys are ordered by `String.compareTo`, which is per code unit.

    A surrogate leads with 0xD800, below every BMP character above it, where Python reads
    U+1F600 as greater. The tree's shape, and so its root, depends on which rule applies.
    """
    assert compare_to("\U0001f600", "�") < 0
    assert "\U0001f600" > "�"
    order = hashmap_order([key + "\U0001f600" for key in colliding(20)])
    assert order[:3] == [
        "AaAaAaAaAaAaAaBBBBBB\U0001f600",
        "AaAaAaAaAaAaAaAaBBBB\U0001f600",
        "AaAaAaAaAaAaAaAaAaAa\U0001f600",
    ]


def test_an_empty_key_iterates_from_bucket_zero():
    """The empty string hashes to 0 and shares bucket 0 with any key that folds there."""
    order = hashmap_order([""] + [f"S{index}" for index in range(20)])
    assert order[0] == ""
    assert len(order) == 21


def test_a_guava_multimap_starts_at_thirty_two_buckets():
    """`ArrayListMultimap.create()` pre-sizes for 12 keys, so its table is 32, not 16.

    `Maps.capacity(12)` is 12/0.75 + 1 = 17, and HashMap rounds an initial capacity up to a power
    of two. Measured on the pinned jar's Guava with five keys chosen to separate the two: the
    multimap yields them in insertion order and a plain HashMap moves S10 to second place.
    """
    keys = ["S6", "S7", "S8", "S9", "S10"]
    assert multimap_order(keys) == ["S6", "S7", "S8", "S9", "S10"]
    assert hashmap_order(keys) == ["S6", "S10", "S7", "S8", "S9"]


def test_the_two_collections_converge_once_they_have_grown():
    """Why this went unnoticed through an ordering audit and eleven reviews.

    Both tables resize by doubling, so after enough insertions they hold the same capacity and
    every later arrangement agrees. Every ordering probe in this project used about a thousand
    keys, where the two are indistinguishable. The difference lives below about 25 keys, and a
    report can still hit its 1,000-sample cap there whenever a rule emits many notices per key.
    """
    thousand = [f"SD{index:04d}" for index in range(1005)]
    assert multimap_order(thousand) == hashmap_order(thousand)
    small = [f"S{index + 6}" for index in range(5)]
    assert multimap_order(small) != hashmap_order(small)


def test_a_composite_key_survives_a_treeified_bin():
    """Eleven grouping keys that share one hash, which a review turned into a crash.

    `Aa` and `BB` hash alike in Java, so a feed can put arbitrarily many timeframe groups in
    one bucket without trying hard: eleven of them treeify the bin, and the tree ordered its
    nodes by `String.compareTo` on what is here a tuple. That raised TypeError, the runner
    turned it into a runtime_exception_in_validator_error, and eleven notices the jar reports
    went missing.

    A non-`Comparable` key never reaches `compareTo` in Java either; it goes to
    `tieBreakOrder`, whose identity hash nothing outside that JVM run can reproduce. So this
    asserts what can be asserted: every key comes back, exactly once. The order in this case
    is deliberately not upstream's, which the module docstring records.
    """
    keys = [(group, "WEEK") for group in colliding(11, width=4)]
    hashes = {auto_value_hash(key) for key in keys}
    assert len(hashes) == 1, "the probe must actually collide, or it tests nothing"
    assert sorted(grouping_by_order(keys, auto_value_hash)) == sorted(keys)


def test_long_keys_use_the_thirty_two_bucket_table():
    """`long_multimap_order`, pinned to the `fast1` probe's measured group order.

    These are six of that feed's trip fingerprints, written in the order the trip-id multimap
    inserts them, which for these six ids is their alphabetical order. The jar reports their
    notices as TB, TJ, TH, TA, TE, TD, and a 16-bucket table gives a different sequence, so
    this is about the capacity as much as about `Long.hashCode`.
    """
    fingerprints = {
        1531072278823761014: "TA",
        545257142897386253: "TB",
        3701293492031017166: "TD",
        5269178458131939922: "TE",
        3490126326072880137: "TH",
        8205400816368101138: "TJ",
    }
    assert [fingerprints[key] for key in long_multimap_order(fingerprints)] == [
        "TB",
        "TJ",
        "TH",
        "TA",
        "TE",
        "TD",
    ]


def test_spread_folds_the_high_bits_down_unsigned():
    """`HashMap.hash` shifts with `>>>`, which for a negative hash code is not Python's `>>`.

    Each expectation is `h ^ (h >>> 16)` worked by hand: -7 is 0xFFFFFFF9, shifted right by
    sixteen without sign gives 0x0000FFFF, and the xor is 0xFFFF0006, which as a signed int is
    -65530. Python's arithmetic shift sign-extends instead and would answer 6, so these five
    values separate the two: the first four disagree and 0x12345678 is the control that must
    not, since a non-negative hash code shifts the same either way.

    Only a `Long` key gets here with a negative hash code. `String.hashCode` is negative about
    half the time in Java, but `string_hash` returns the unsigned value, so the map's string
    callers never exposed this.
    """
    assert [spread(code) for code in (-7, -1, -65536, -2147483648, 0x12345678)] == [
        -65530,
        -65536,
        -1,
        -2147450880,
        305415244,
    ]
