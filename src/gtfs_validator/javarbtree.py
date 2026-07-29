"""The red-black mechanics `HashMap.TreeNode` inherits, split out from the bin model.

Nothing here knows about buckets or iteration order. It is the node, the two rotations and
`balanceInsertion`, transcribed from the JDK so that `javatree` can ask what shape an
insertion leaves and, from that, which node ends up as root.

Split from `javatree` when that file passed 300 lines, along the seam that was already there:
this half is a textbook red-black tree, and the half next door is the part where Java's
iteration follows a *list* the tree perturbs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(eq=False)
class Node:
    """One entry. `hash` is the spread hash as a signed 32-bit int, as Java stores it.

    `nxt`/`prev` are the list links `keySet()` walks, spelled short of `next` because that
    names a builtin. Holding the list as links rather than as a Python list is not just
    fidelity: splicing into a list meant an `index()` scan per insertion, which is quadratic
    in the bin's depth. Measured on equal-hash keys before the change: 0.04 s for 1,024,
    2.16 s for 16,384, which extrapolates past the 60 s scale ceiling at 100,000. The
    differential could not have caught it, because every probe feed is small enough to be
    fast whichever way this is written.
    """

    hash: int
    key: str
    left: Node | None = field(default=None, repr=False)
    right: Node | None = field(default=None, repr=False)
    parent: Node | None = field(default=None, repr=False)
    nxt: Node | None = field(default=None, repr=False)
    prev: Node | None = field(default=None, repr=False)
    red: bool = False


def _rotate_left(root: Node, pivot: Node) -> Node:
    right = pivot.right
    if right is None:
        return root
    pivot.right = right.left
    if pivot.right is not None:
        pivot.right.parent = pivot
    right.parent = pivot.parent
    if right.parent is None:
        root = right
        root.red = False
    elif right.parent.left is pivot:
        right.parent.left = right
    else:
        right.parent.right = right
    right.left = pivot
    pivot.parent = right
    return root


def _rotate_right(root: Node, pivot: Node) -> Node:
    left = pivot.left
    if left is None:
        return root
    pivot.left = left.right
    if pivot.left is not None:
        pivot.left.parent = pivot
    left.parent = pivot.parent
    if left.parent is None:
        root = left
        root.red = False
    elif left.parent.right is pivot:
        left.parent.right = left
    else:
        left.parent.left = left
    left.right = pivot
    pivot.parent = left
    return root


def balance_insertion(root: Node, node: Node) -> Node:
    """`HashMap.balanceInsertion`, transcribed including its null guards.

    The guards matter: they are the reason a rotation can leave a red parent in place,
    and the resulting shape decides the root, which decides the first key iterated.
    """
    node.red = True
    while True:
        parent = node.parent
        if parent is None:
            node.red = False
            return node
        grandparent = parent.parent
        if not parent.red or grandparent is None:
            return root
        if parent is grandparent.left:
            uncle = grandparent.right
            if uncle is not None and uncle.red:
                uncle.red = False
                parent.red = False
                grandparent.red = True
                node = grandparent
                continue
            if node is parent.right:
                node = parent
                root = _rotate_left(root, node)
                parent = node.parent
                grandparent = None if parent is None else parent.parent
            if parent is not None:
                parent.red = False
                if grandparent is not None:
                    grandparent.red = True
                    root = _rotate_right(root, grandparent)
        else:
            uncle = grandparent.left
            if uncle is not None and uncle.red:
                uncle.red = False
                parent.red = False
                grandparent.red = True
                node = grandparent
                continue
            if node is parent.left:
                node = parent
                root = _rotate_right(root, node)
                parent = node.parent
                grandparent = None if parent is None else parent.parent
            if parent is not None:
                parent.red = False
                if grandparent is not None:
                    grandparent.red = True
                    root = _rotate_left(root, grandparent)


