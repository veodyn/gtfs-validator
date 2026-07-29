"""`util.shape`: matching a trip's stops to the shape its trip references.

Ported from upstream's `util/shape` package, which one validator uses and which produces four
notice codes. The split here follows the Java: `shape` and `stops` build the two point sequences,
`matcher` assigns one to the other, `matches` holds what they exchange.

Nothing in this package reads a notice code or builds a notice. The rules do that, so that the
geometry can be tested against the S2 library without a feed, and so that the four codes share one
pass rather than four.
"""
