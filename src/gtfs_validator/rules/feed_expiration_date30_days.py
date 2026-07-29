"""FeedExpirationDateValidator, second branch: the feed expires within a month.

Never fires alongside the 7-day notice: upstream returns after that branch, and
expiration_context reproduces the exclusion rather than each module re-deriving
the other's boundary.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.expiration import EXPIRY_UPCOMING_DAYS, expiration_context
from gtfs_validator.rules.registry import rule


@rule(code="feed_expiration_date30_days", severity=Severity.WARNING, filename="feed_info.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    context = expiration_context(row, ctx, EXPIRY_UPCOMING_DAYS)
    if context is not None:
        yield Notice("feed_expiration_date30_days", Severity.WARNING, context)
