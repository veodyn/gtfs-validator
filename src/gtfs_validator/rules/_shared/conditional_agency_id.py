"""The agency_id checks that FareAttributeAgencyIdValidator and RouteAgencyIdValidator share.

Two tables carry an optional agency_id whose absence upstream judges by how many agencies exist:
one agency makes it a recommendation, more than one makes it required. The same row therefore draws
`missing_recommended_field` or `missing_required_agency_id` depending on a *different* table's size,
which is why both codes read this helper rather than each table separately.

Found late, and the way it was found is the lesson: a probe built for another rule happened to
include fare_attributes.txt, a table no earlier probe carried, and the jar immediately reported a
notice we did not. `missing_recommended_field` has four upstream emitters and this module is the
third and fourth; the rule's own docstring had said "two validators, one code" and listed two,
which read like a closed set and stopped anyone looking.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.rules._shared.agency_consistency import agencies

AGENCY_ID = "agency_id"
# The two tables whose agency_id is conditional on the agency count, in the order the jar reports
# them. Measured, after a first version put routes first and said so in a comment: on a feed with
# both, the jar's samples run fare_attributes then routes. Above the 1,000-sample cap that decides
# which notices survive, so it is the contract rather than a detail.
CONDITIONAL_TABLES = ("fare_attributes.txt", "routes.txt")


def rows_missing_agency_id(feed) -> Iterator[tuple[str, dict, bool]]:
    """Each row of those tables with no agency_id, and whether the feed has several agencies.

    Yields `(filename, row, several)` in the order the jar reports them, fare attributes before
    routes. A first version asserted the opposite in a comment and was measured wrong.
    """
    count = len(agencies(feed))
    # With *no* agencies at all the jar reports neither notice, so this is not simply
    # `count > 1` deciding between two branches: zero is a third case. Measured on a feed whose
    # agency.txt is a bare header and whose routes.txt and fare_attributes.txt each leave
    # agency_id blank, where the jar is silent and reading `0 > 1` as "recommend it" reported two
    # notices it does not.
    #
    # This comment first guessed the mechanism: that an empty required file leaves its container
    # non-parsable so upstream skips every validator injected with it. **A review disproved that.**
    # `UrlConsistencyValidator` takes the same agency container and still runs on the same feed.
    # The four states were measured (absent is MISSING_FILE, zero bytes EMPTY_FILE, a bad sole row
    # UNPARSABLE_ROWS, and a bare header parses with no entities), and none of them explains the
    # silence. So the reason is still unknown and the code follows the measurement, which is the
    # honest position rather than the one this comment held for a commit.
    if count == 0:
        return
    several = count > 1
    for filename in CONDITIONAL_TABLES:
        for row in feed.rows(filename):
            # `!route.hasAgencyId()` and `!fare.hasAgencyId()`: presence, not truthiness.
            if row.get(AGENCY_ID) is None:
                yield filename, row, several


# FareLegJoinRuleValidator's conditional pair: naming one stop end obliges the other. Found by an
# emitter sweep over every code already in the manifest, which is the check that catches a code
# reporting *fewer* notices than the jar rather than different ones.
FARE_LEG_JOIN_RULES = "fare_leg_join_rules.txt"
STOP_ENDS = (("from_stop_id", "to_stop_id"), ("to_stop_id", "from_stop_id"))


def rows_missing_stop_peer(feed) -> Iterator[tuple[dict, str]]:
    """Each fare leg join rule naming one stop end but not the other, with the absent field."""
    for row in feed.rows(FARE_LEG_JOIN_RULES):
        for present, absent in STOP_ENDS:
            # `hasFromStopId() && !hasToStopId()`, and the mirror. Both presence.
            if row.get(present) is not None and row.get(absent) is None:
                yield row, absent
                break
