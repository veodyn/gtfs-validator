"""The reads AgencyConsistencyValidator's four branches share.

Upstream is one FileValidator emitting four codes; here each code is its own module,
so the walk of agency.txt and the "which agency sets the expectation" rule live here
once. Getting that rule wrong in one of four copies is exactly the drift the
`_shared` convention exists to prevent.

The expectation is positional, not a majority: the **first** agency's timezone is
`expected`, and the first agency that *has* a language sets the expected language.
An agency with a blank language is skipped entirely rather than counting as a
mismatch.

agency.txt holds a handful of rows in every real feed, so materialising it is safe
here in a way it would not be for stop_times.txt.
"""

from __future__ import annotations

FILENAME = "agency.txt"
_CACHE_KEY = "agency_consistency.rows"


def agencies(feed) -> list[dict]:
    """Every loaded agency row, in file order, cached for the four rules.

    A table upstream refused to index reads as empty here, which is what makes a
    feed whose agency.txt has a missing required field draw none of these notices:
    measured, and the reason an early probe looked silently wrong.
    """
    cached = feed.cache.get(_CACHE_KEY)
    if cached is None:
        cached = list(feed.rows(FILENAME))
        feed.cache[_CACHE_KEY] = cached
    return cached
