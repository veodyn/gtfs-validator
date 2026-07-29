"""`StopToShapeMatch` and `Problem`, the two things stop-to-shape matching produces.

Both are ported as mutable objects because upstream's algorithm is written around mutation:
`matchesFromLocation` keeps one running best match, copies it into a list when the shape turns
away, and then clears it in place. A frozen value type would force that loop to be rewritten, and
rewriting the loop is how a local-minimum count silently changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from gtfs_validator.s2point import Point

# `new S2Point()`, the zero vector a match starts out holding. It is never read before a match is
# kept, but it is what `location` is until then.
ORIGIN: Point = (0.0, 0.0, 0.0)


class ProblemType(Enum):
    """`Problem.ProblemType`. Three kinds, four notice codes: the too-far kind reports as either
    the geo or the user-distance code depending on which pass found it."""

    STOP_TOO_FAR_FROM_SHAPE = "stop_too_far_from_shape"
    STOP_HAS_TOO_MANY_MATCHES = "stop_has_too_many_matches"
    STOPS_MATCH_OUT_OF_ORDER = "stops_match_out_of_order"


@dataclass
class Match:
    """`StopToShapeMatch`: where on a shape a stop was matched, and how far away that is.

    `geo_distance_to_shape` doubles as the "no match yet" flag: `clear_best_match` sets it to
    positive infinity and `has_best_match` tests against that, which is why the field cannot be
    given a sentinel of its own.
    """

    index: int = 0
    user_distance: float = 0.0
    geo_distance: float = 0.0
    geo_distance_to_shape: float = math.inf
    location: Point = ORIGIN

    def copy(self) -> Match:
        """`new StopToShapeMatch(that)`, which the local-minimum loop stores and then clears."""
        return Match(
            index=self.index,
            user_distance=self.user_distance,
            geo_distance=self.geo_distance,
            geo_distance_to_shape=self.geo_distance_to_shape,
            location=self.location,
        )

    def clear_best_match(self) -> None:
        self.geo_distance_to_shape = math.inf

    def has_best_match(self) -> bool:
        return self.geo_distance_to_shape != math.inf

    def keep_best_match(self, location: Point, geo_distance_to_shape: float, index: int) -> None:
        """Replace the match only on a strictly smaller distance.

        Strictly: two segments meeting at a vertex give distances that differ in their tenth
        digit, and `<=` would hand the match to the later segment. The reported distance would be
        the same and the reported shape index would not.
        """
        if geo_distance_to_shape < self.geo_distance_to_shape:
            self.geo_distance_to_shape = geo_distance_to_shape
            self.location = location
            self.index = index


@dataclass(frozen=True)
class Problem:
    """One matching failure, holding the `stop_times.txt` rows a notice will name.

    `match_count` is meaningful only for the too-many-matches kind and `previous_*` only for the
    out-of-order kind, exactly as upstream's single constructor with its nulls and zero.
    """

    type: ProblemType
    stop_time: dict
    match: Match
    match_count: int = 0
    previous_stop_time: dict | None = None
    previous_match: Match | None = None


@dataclass
class MatchResult:
    """`StopToShapeMatcher.MatchResult`.

    The validator reads only `problems`. `matches` is kept because the matcher's own control flow
    turns on whether it is empty, and dropping it would hide that from a reader comparing this
    against the Java.
    """

    matches: list[Match] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
