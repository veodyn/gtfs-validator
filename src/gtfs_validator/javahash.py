"""`java.util.HashMap` iteration order, for the notices whose samples are capped.

Several upstream validators collect into a `HashMap` and then iterate `keySet()`, so the
notices come out in the map's bucket order. That order looked like an implementation detail
worth ignoring, and this codebase said so in a comment: the differential compares samples as
a sorted multiset, so order does not matter.

That was wrong above the cap. A report keeps the first 1,000 notices per code and counts the
rest, so when there are more than 1,000 the *order decides which 1,000 are kept*. Measured on
a feed with 1,005 unsorted trips: both sides report `totalNotices: 1005`, the jar's samples
begin T0714, T0956, T0715 and ours began T0000, T0001, T0002, and no amount of sorting
afterwards makes those the same set.

The order is reproducible, which is why this exists rather than a divergence entry. HashMap is
specified closely enough to simulate: a table of 16 buckets, index `(capacity - 1) & spread`,
insertion appending to a bucket's list, and a doubling resize once size passes three quarters
of capacity, which splits each bucket while preserving relative order.

A deep bucket becomes a red-black tree, which reorders it. That case was left out at first and
`bucket_overflowed` reported it so a caller could say so rather than quietly disagreeing. No
caller ever did, and the gap was real: a corpus of 1,024 keys sharing one `hashCode` disagreed
with the JDK from the first sample. `gtfs_validator.javatree` now models the tree, so for a string
key this file has no unreproduced case left and no caller has to ask.

`grouping_by_order` takes keys that are not strings, and there the tree's tie-break is Java's
identity hash rather than a comparison. That one case is not reproduced and cannot be:
reproducing it needs 1,024 keys sharing one hashCode.

Verified against the pinned JDK over 100 corpora by tools/diff_hashmap_against_jdk.py, which
generates them to cross the thresholds rather than to match what is implemented here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from gtfs_validator.javatree import UNTREEIFY_THRESHOLD, Node, TreeBin

_MASK = 0xFFFFFFFF
_SIGN_BIT = 0x80000000
_INITIAL_CAPACITY = 16
# `ArrayListMultimap.create()` pre-sizes its backing map for Guava's default of 12 expected
# keys. `Maps.capacity(12)` is 12/0.75 + 1 = 17, and HashMap rounds an initial capacity up to a
# power of two, so the table starts at 32 buckets rather than 16. Measured on the pinned jar's
# Guava with keys S6 to S10, where the multimap yields S6 S7 S8 S9 S10 and a plain HashMap
# yields S6 S10 S7 S8 S9.
_MULTIMAP_CAPACITY = 32
# The multiplier AutoValue's generated hashCode folds with.
_AUTO_VALUE_PRIME = 1000003
_LOAD_FACTOR_NUMERATOR = 3
_LOAD_FACTOR_DENOMINATOR = 4
# TREEIFY_THRESHOLD and MIN_TREEIFY_CAPACITY.
_TREEIFY_THRESHOLD = 8
_MIN_TREEIFY_CAPACITY = 64

_Bin = list[Node] | TreeBin


def string_hash(value: str) -> int:
    """`String.hashCode()`: 31-based, over UTF-16 code units, wrapping at 32 bits.

    Code units rather than code points, so a non-BMP character contributes its two
    surrogates. The same distinction that made `String.length()` a recurring defect here.
    """
    result = 0
    for character in value:
        code = ord(character)
        if code > 0xFFFF:
            # Java stores this as a surrogate pair and hashes both halves.
            offset = code - 0x10000
            units = (0xD800 + (offset >> 10), 0xDC00 + (offset & 0x3FF))
        else:
            units = (code,)
        for unit in units:
            result = (result * 31 + unit) & _MASK
    return result


def auto_value_hash(components: Iterable[str]) -> int:
    """The `hashCode` AutoValue generates: seed 1, then `*= 1000003` and `^=` each component.

    Upstream groups by a generated `@AutoValue` key in several validators, and the fold is what
    decides that map's iteration order. Confirmed against the jar on `tfov`, whose empty-group
    overlap is reported before its G1 overlap: only this fold, with the components in this
    order, puts the empty group in the earlier bucket.
    """
    result = 1
    for component in components:
        result = (result * _AUTO_VALUE_PRIME) & _MASK
        result ^= string_hash(component)
    return result


def spread(hash_code: int) -> int:
    """`HashMap.hash`: fold the high bits down so they affect the bucket index.

    The shift is Java's `>>>`, which is why the argument is masked first. Python's `>>` is
    arithmetic and sign-extends, so a negative hash code folds in ones where Java folds in
    zeros and the top half of the result comes out inverted. `String.hashCode` is negative
    about half the time in Java, but this project holds it unsigned, so nothing noticed until
    `long_hash` arrived returning a signed value.

    Returned signed, as Java holds it: a treeified bin compares hashes with `<` before
    falling back to the key, and an unsigned comparison orders the negatives wrongly.

    The bucket index cannot see either mistake. It reads the low bits, and those agree under
    both shifts, so only a tree deep enough to compare hashes can tell the two apart. The
    corpus that does is `mixed-sign-hashes` in tools/_hashmap_corpora.py.
    """
    unsigned = hash_code & _MASK
    folded = unsigned ^ (unsigned >> 16)
    return folded - (_MASK + 1) if folded & _SIGN_BIT else folded


def hashmap_order(keys: Iterable[str]) -> list[str]:
    """The keys in the order `new HashMap<>().keySet()` would yield them.

    For a map the validator builds itself. A generated table container's `by...IdMap()` is a
    Guava multimap and starts at a different capacity, so it needs `multimap_order` instead:
    picking by what upstream constructs is a per-rule question, not a house style.

    `keys` must be given in insertion order and must not repeat: within a bucket, order
    follows insertion, so the sequence matters.
    """
    return _order(keys, _INITIAL_CAPACITY)


def multimap_order(keys: Iterable[str]) -> list[str]:
    """The keys in the order `Multimaps.asMap(container.by...IdMap())` would yield them.

    The generated table containers index with `ArrayListMultimap.create()`, whose backing map is
    pre-sized for 12 keys and therefore starts at 32 buckets. The difference from a plain
    `HashMap` is invisible once a map has grown past it, which is exactly why it survived an
    audit: every ordering probe in this project used about a thousand keys, and by then both
    have resized to the same capacity and agree completely. It shows up on a handful of keys,
    and a report can still reach its 1,000-sample cap on a handful of keys whenever a rule emits
    many notices per key.
    """
    return _order(keys, _MULTIMAP_CAPACITY)


def long_hash(value: int) -> int:
    """`Long.hashCode`: the two halves folded together, as a signed 32-bit int."""
    unsigned = value & 0xFFFFFFFFFFFFFFFF
    folded = (unsigned ^ (unsigned >> 32)) & _MASK
    return folded - (_MASK + 1) if folded & _SIGN_BIT else folded


def long_multimap_order(keys: Iterable[int]) -> list[int]:
    """The keys in the order a `Long`-keyed `ArrayListMultimap` would yield them.

    `StopTimeTravelSpeedValidator` groups trips into `ArrayListMultimap.create()` under a
    64-bit fingerprint, so the table is the 32-bucket one `multimap_order` models and the hash
    is `Long.hashCode` rather than `String.hashCode`. Confirmed on a feed of eleven trips
    whose groups the jar reports in an order that is neither file order nor sorted.
    """
    table = _Table(_MULTIMAP_CAPACITY)
    for key in keys:
        table.put(key, long_hash(key))
    return table.keys()


def grouping_by_order(keys: Iterable[object], hash_of: Callable[[object], int]) -> list[object]:
    """The keys in the order a `Collectors.groupingBy` map would yield them.

    Same table as `hashmap_order`, but the key need not be a string and its hash is supplied
    rather than derived. Upstream's grouping keys are often generated `@AutoValue` classes
    whose `hashCode` is a fold over their components, so the caller models that fold and this
    models the table.

    Two limits, both measured against the pinned JDK:

    - `groupingBy` inserts through `computeIfAbsent`, whose bucket arrangement is not quite
      `put`'s. The measured residue is one element in a 1,005-notice probe.
    - A bin that treeifies orders its nodes by comparing keys, and a non-`Comparable` key
      sends Java to `identityHashCode`, which nothing outside that run can reproduce. This
      settles the tie at -1, as `tieBreakOrder` itself does when the identity hashes match, so
      the order is deterministic and is not upstream's.

    A review had to correct the second point twice over. It was first written as unreachable,
    on the reasoning that nine keys must collide on one bucket; `Aa` and `BB` hash alike in
    Java, so eleven colliding timeframe groups are a feed anyone can write. It was then
    written as falling back to insertion order, and it did not: the tree compared a tuple with
    `String.compareTo` and raised, which cost the eleven notices the jar reports.
    """
    table = _Table(_INITIAL_CAPACITY)
    for key in keys:
        table.put(key, hash_of(key))
    return table.keys()


def _order(keys: Iterable[str], capacity: int) -> list[str]:
    table = _Table(capacity)
    for key in keys:
        table.put(key)
    return table.keys()


class _Table:
    """The parts of `HashMap` that decide iteration order, and nothing else."""

    def __init__(self, capacity: int = _INITIAL_CAPACITY) -> None:
        self.capacity = capacity
        self.bins: list[_Bin | None] = [None] * self.capacity
        self.size = 0

    def keys(self) -> list[str]:
        return [
            node.key
            for bucket in self.bins
            if bucket is not None
            for node in (bucket.order() if isinstance(bucket, TreeBin) else bucket)
        ]

    def put(self, key: object, hash_code: int | None = None) -> None:
        # A string key hashes itself; a composite key's hash is the caller's business, since
        # it comes from a generated hashCode this module has no way to derive.
        node = Node(spread(string_hash(key) if hash_code is None else hash_code), key)
        index = (self.capacity - 1) & node.hash
        bucket = self.bins[index]
        if bucket is None:
            self.bins[index] = [node]
        elif isinstance(bucket, TreeBin):
            bucket.put(node)
        else:
            # Java counts the nodes it walks past and treeifies when it walked eight, so
            # the bin holds nine by then. One off here moves the first tree a whole key.
            walked = len(bucket)
            bucket.append(node)
            if walked >= _TREEIFY_THRESHOLD:
                self._treeify_bin(index)
        self.size += 1
        if self.size * _LOAD_FACTOR_DENOMINATOR > self.capacity * _LOAD_FACTOR_NUMERATOR:
            self._resize()

    def _treeify_bin(self, index: int) -> None:
        """`treeifyBin`, whose first branch is the one that surprises.

        Under 64 buckets it resizes instead of treeifying, so a table filling up with
        equal-hash keys spends two of these on growth before any tree appears.
        """
        if self.capacity < _MIN_TREEIFY_CAPACITY:
            self._resize()
            return
        bucket = self.bins[index]
        if isinstance(bucket, list):
            self.bins[index] = TreeBin(bucket)

    def _resize(self) -> None:
        bit = self.capacity
        self.capacity *= 2
        moved: list[_Bin | None] = [None] * self.capacity
        for index, bucket in enumerate(self.bins):
            if bucket is None:
                continue
            if isinstance(bucket, TreeBin):
                self._split_tree(moved, bucket, index, bit)
                continue
            # Walking in order and appending preserves each bucket's relative order,
            # which is what HashMap's lo/hi split does.
            for node in bucket:
                target = index + bit if node.hash & bit else index
                existing = moved[target]
                if existing is None:
                    moved[target] = [node]
                else:
                    existing.append(node)  # type: ignore[union-attr]
        self.bins = moved

    def _split_tree(self, moved: list[_Bin | None], bucket: TreeBin, index: int, bit: int) -> None:
        """`TreeNode.split`, including the two conditions that reorder a half or do not.

        A half of six or fewer becomes a plain list, keeping its order. A larger half
        rebuilds its tree *only when the other half is non-empty*, and rebuilding moves the
        new root to the front. So a bin whose keys share one hash never moves and never
        rebuilds: it arrives at the far side of every resize in the order it already had.
        """
        low, high = bucket.split(bit)
        for target, half, other in ((index, low, high), (index + bit, high, low)):
            if not half:
                continue
            if len(half) <= UNTREEIFY_THRESHOLD:
                moved[target] = half
            elif other:
                moved[target] = TreeBin(half)
            else:
                # Java keeps the tree it already has: same nodes, same root, same order.
                bucket.relink(half)
                moved[target] = bucket
