"""The URL index UrlConsistencyValidator builds, shared by its three codes.

One validator injected with agency.txt, routes.txt and stops.txt emits all three codes, and that
matters more than it looks:

- **Gates.** Upstream skips a FileValidator when *any* injected container has a non-parsable
  status, so a broken routes.txt silences `same_stop_and_agency_url` too, a code that never reads
  routes.txt. Measured on a feed whose routes.txt carries a short row: all three codes vanish.
  Hence `validator_skipped`, an explicit guard naming all three tables. Letting each code be
  gated by whichever tables it happens to read would report two codes the jar does not, and the
  coupling would be invisible at the point where it matters.
- **Order.** Everything here is file order. Upstream walks `getEntities()` and looks URLs up in an
  `ArrayListMultimap`, whose values keep insertion order, so no `hashmap_order` is involved. A URL
  shared by two agencies draws one notice per agency, in agency file order.
- **Matching.** The key is `Ascii.toLowerCase`, which folds A-Z and nothing else, while the notice
  reports the URL as written. Both halves are measured: a route whose URL is upper case matches a
  lower-case agency URL and reports its own casing, and a pair differing only in `Ä` versus `ä`
  does not match at all.
"""

from __future__ import annotations

from gtfs_validator.javatext import ascii_to_lower

AGENCY = "agency.txt"
ROUTES = "routes.txt"
STOPS = "stops.txt"
AGENCY_URL = "agency_url"
ROUTE_URL = "route_url"
STOP_URL = "stop_url"
# The three containers the validator's constructor takes, and so the three that gate it.
INJECTED = (AGENCY, ROUTES, STOPS)


def validator_skipped(feed) -> bool:
    """Whether upstream would decline to run the validator these three codes share."""
    return any(feed.dependency_failed(filename) for filename in INJECTED)


def by_url(feed, filename: str, column: str) -> dict[str, list[dict]]:
    """Rows that declare a URL, grouped under its ASCII-lowercased form, in file order."""
    grouped: dict[str, list[dict]] = {}
    for row in feed.rows(filename):
        url = row.get(column)
        if url is None:
            continue
        grouped.setdefault(ascii_to_lower(url), []).append(row)
    return grouped


def matches(index: dict[str, list[dict]], url: str) -> list[dict]:
    """Every row sharing `url`, folded the way upstream's multimap key is."""
    return index.get(ascii_to_lower(url), [])
