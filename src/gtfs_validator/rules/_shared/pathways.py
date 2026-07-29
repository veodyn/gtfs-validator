"""The stops-and-pathways reads the pathway validators share.

Three validators read the same two tables from different directions: by stop id, by
parent station, by from_stop_id and by to_stop_id. Upstream gets those as prebuilt
container indexes; here they are built once per feed and cached, because pathways.txt and
stops.txt are both small enough to index in memory and rebuilding four maps per rule is
the sort of cost the differential cannot see.

`stops.txt` is read through the gated `rows()`: all three are FileValidators, so a stops
table upstream refused to index leaves them with nothing to say.
"""

from __future__ import annotations

FROM_STOP_ID = "from_stop_id"
TO_STOP_ID = "to_stop_id"
_CACHE_KEY = "pathways.index"


class PathwayIndex:
    """Stops by id, stops by parent, and pathways by each endpoint."""

    def __init__(self, feed) -> None:
        self.stops: dict[str, dict] = {}
        self.children: dict[str, list[dict]] = {}
        for row in feed.rows("stops.txt"):
            stop_id = row.get("stop_id")
            if stop_id is not None:
                # First wins, matching a container index built over a table whose
                # duplicate ids were already reported and dropped.
                self.stops.setdefault(stop_id, row)
            # Keyed by `parentStation()`, which is "" for a row with no parent rather than omitted.
            # `byParentStation("")` upstream therefore returns every root-level stop, which is only
            # observable for a location whose own `stop_id` is "": such a platform looks as though it
            # has children and is exempt from `pathway_unreachable_location`. Measured on a feed
            # whose platform id is a quoted whitespace cell, where the jar is silent and an index
            # that omitted these reported it. `pathway_to_platform_with_boarding_areas` reads the
            # same map, so omitting them was one defect in two rules.
            self.children.setdefault(row.get("parent_station") or "", []).append(row)
        self.pathways: list[dict] = list(feed.rows("pathways.txt"))
        self.by_from: dict[str, list[dict]] = {}
        self.by_to: dict[str, list[dict]] = {}
        for row in self.pathways:
            for field, index in ((FROM_STOP_ID, self.by_from), (TO_STOP_ID, self.by_to)):
                value = row.get(field)
                if value is not None:
                    index.setdefault(value, []).append(row)


def index_of(feed) -> PathwayIndex:
    cached = feed.cache.get(_CACHE_KEY)
    if cached is None:
        cached = PathwayIndex(feed)
        feed.cache[_CACHE_KEY] = cached
    return cached
