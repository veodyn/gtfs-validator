"""What FareTransferRuleTransferCountValidator's three notices agree on.

A rule whose two leg groups are the same is a *self* transfer, and only those may
carry a `transfer_count`. The three notices partition that: a self transfer with an
out-of-range count, a self transfer with none, and a non-self transfer with one.
Sharing the predicate keeps the three modules from disagreeing about what "self" means.
"""

from __future__ import annotations

FROM_GROUP = "from_leg_group_id"
TO_GROUP = "to_leg_group_id"
COUNT = "transfer_count"


def is_self_transfer(row: dict) -> bool:
    """Both leg groups present and equal, as upstream's Objects.equals guard requires."""
    from_group, to_group = row.get(FROM_GROUP), row.get(TO_GROUP)
    return from_group is not None and to_group is not None and from_group == to_group
