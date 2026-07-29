"""FeedExpirationDateValidator, first branch: the feed expires within a week."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.expiration import EXPIRY_SOON_DAYS, expiration_context
from gtfs_validator.rules.registry import rule


@rule(code="feed_expiration_date7_days", severity=Severity.WARNING, filename="feed_info.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    context = expiration_context(row, ctx, EXPIRY_SOON_DAYS)
    if context is not None:
        yield Notice("feed_expiration_date7_days", Severity.WARNING, context)
