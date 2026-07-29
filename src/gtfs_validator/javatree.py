"""`HashMap.TreeNode`: the red-black bin a deep bucket turns into, and its iteration order.

A bucket holding eight entries in a table of at least 64 becomes a red-black tree. The
tree is not what iteration follows: a `TreeNode` keeps the `next`/`prev` links of the
list it replaced, and `keySet()` still walks those. So iteration order is a *list* order
that tree operations perturb, in two places and only two:

- `putTreeVal` splices a new node in immediately after the node it attached to, rather
  than at the end of the list.
- `moveRootToFront` then lifts the tree's root to the head of the list, so whichever key
  balancing left at the root iterates first.

That is why the order is reproducible without simulating the tree's shape for its own
sake: the shape is needed only to know which node a new key attaches to and which node
ends up as root. For a `String` key, equal hashes are ordered by `String.compareTo`, which
never returns zero for distinct strings, so `tieBreakOrder`'s identity hash is unreachable
and the order is both deterministic and upstream's.

A `Long` key, which arrives through `javahash.long_multimap_order`, is `Comparable` too and
compares numerically, so its order is reproduced as exactly as a string's. A key that is
neither is the exception, and it arrives through `javahash.grouping_by_order`. Java sends it
straight to `tieBreakOrder`, whose identity hash nothing outside that run can reproduce, so
`_direction` settles the tie the way `tieBreakOrder` does when the hashes match.
Deterministic, and deliberately not upstream's.

The red-black mechanics themselves are in `gtfs_validator.javarbtree`, which this drives.

Measured against the pinned JDK by tools/diff_hashmap_against_jdk.py. Two thresholds in
that corpus are worth naming, because neither follows from the constants alone:

- With nothing but equal-hash keys the first tree appears at the *eleventh*, not the eighth.
  Two things push it out: `putVal` treeifies when it walked eight nodes, so the bin holds
  nine by then, and `treeifyBin` under 64 buckets resizes instead, twice, carrying capacity
  from 16 to 64. The eleventh insertion is the first to find both conditions met. Measured,
  not deduced: this docstring first said the tenth.
- A bin whose keys share one hash never splits, so it keeps its tree across every later
  resize untouched. Only a bin of differing hashes reaches the branch that rebuilds a
  tree or drops it back to a list.
"""

from __future__ import annotations

from gtfs_validator.javarbtree import Node, balance_insertion
from gtfs_validator.javatext import compare_to

# UNTREEIFY_THRESHOLD: a split leaving this many or fewer becomes a plain list again.
UNTREEIFY_THRESHOLD = 6


def _direction(node_hash: int, key: object, other: Node) -> int:
    """Which way a key descends past `other`: hash first, then the key comparison.

    Three kinds of key reach this, and what decides is whether Java's key type is
    `Comparable`, not whether this file finds it convenient:

    - A `String` is, so Java uses `compareTo`, and distinct strings never tie, which makes
      `tieBreakOrder` unreachable for them.
    - A `Long` is too, and compares numerically. That case arrives through
      `javahash.long_multimap_order`, whose keys are trip fingerprints. A review found this
      returning -1 for them, which reversed two groups against Guava once a bin treeified.
      Reaching it needs nine fingerprints in one bucket, which is a big feed rather than an
      impossible one, and above the 1,000-sample cap the order decides what is kept.
    - A generated grouping key is **not** `Comparable`, and never reaches `compareTo` at all:
      Java goes straight to `tieBreakOrder`, which compares `System.identityHashCode` and
      settles a tie at -1. Nothing outside that JVM run can reproduce an identity hash, so
      this returns the -1 that `tieBreakOrder` itself falls back to. That order is
      deterministic and is **not** upstream's, which is a deliberate difference.
    """
    if other.hash > node_hash:
        return -1
    if other.hash < node_hash:
        return 1
    if isinstance(key, str) and isinstance(other.key, str):
        return compare_to(key, other.key)
    # bool is an int subclass in Python and never a key here, so this needs no guard against
    # it; Java's Long.compareTo is the sign of the difference, which is Python's comparison.
    if isinstance(key, int) and isinstance(other.key, int):
        return (key > other.key) - (key < other.key)
    return -1


class TreeBin:
    """A treeified bin, holding both the tree and the list `keySet()` iterates."""

    def __init__(self, nodes: list[Node]) -> None:
        self.head: Node = nodes[0]
        self.root: Node | None = None
        self.relink(nodes)
        self.treeify()

    def relink(self, nodes: list[Node]) -> None:
        """Rebuild the list links over `nodes`, which a split hands over in order."""
        self.head = nodes[0]
        previous: Node | None = None
        for node in nodes:
            node.prev = previous
            node.nxt = None
            if previous is not None:
                previous.nxt = node
            previous = node

    def order(self) -> list[Node]:
        """The bin in iteration order: the list, not the tree."""
        walked = []
        node: Node | None = self.head
        while node is not None:
            walked.append(node)
            node = node.nxt
        return walked

    def treeify(self) -> None:
        """`TreeNode.treeify`: insert the list into a fresh tree, then move the root up.

        Called on a bin reaching the threshold and again on each half of a split, which
        is why it rebuilds from the current list rather than assuming an empty one.
        """
        root: Node | None = None
        for node in self.order():
            node.left = node.right = None
            if root is None:
                node.parent = None
                node.red = False
                root = node
                continue
            walk = root
            while True:
                direction = _direction(node.hash, node.key, walk)
                parent = walk
                walk = parent.left if direction <= 0 else parent.right
                if walk is None:
                    node.parent = parent
                    if direction <= 0:
                        parent.left = node
                    else:
                        parent.right = node
                    root = balance_insertion(root, node)
                    break
        self.root = root
        self._move_root_to_front()

    def put(self, node: Node) -> None:
        """`TreeNode.putTreeVal`: attach the node, then splice it in after its parent."""
        walk = self.root
        if walk is None:  # An empty tree cannot occur through the public path.
            self.relink([*self.order(), node])
            self.root = node
            return
        while True:
            direction = _direction(node.hash, node.key, walk)
            parent = walk
            walk = parent.left if direction <= 0 else parent.right
            if walk is None:
                node.parent = parent
                if direction <= 0:
                    parent.left = node
                else:
                    parent.right = node
                # The list position is *after the parent*, not at the end. This is the
                # step that makes a treeified bin's order unlike an insertion order.
                following = parent.nxt
                node.prev = parent
                node.nxt = following
                parent.nxt = node
                if following is not None:
                    following.prev = node
                self.root = balance_insertion(self.root, node)
                self._move_root_to_front()
                return

    def _move_root_to_front(self) -> None:
        root = self.root
        if root is None or self.head is root:
            return
        if root.nxt is not None:
            root.nxt.prev = root.prev
        if root.prev is not None:
            root.prev.nxt = root.nxt
        root.prev = None
        root.nxt = self.head
        self.head.prev = root
        self.head = root

    def split(self, bit: int) -> tuple[list[Node], list[Node]]:
        """`TreeNode.split`: partition the list by one hash bit, preserving order.

        The caller decides what to do with each half, because the decision needs the
        table: a half of six or fewer becomes a list, and a half only rebuilds its tree
        when the other half is non-empty. A bin of equal-hash keys therefore comes
        through a resize with its tree, and its order, untouched.
        """
        walked = self.order()
        low = [node for node in walked if not node.hash & bit]
        high = [node for node in walked if node.hash & bit]
        return low, high
