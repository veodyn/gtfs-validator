"""The synthetic feed `measure_scale.py` measures against.

Nothing in this file measures anything, and nothing in it decides a size: the dimensions and their
rationale live in `_scale_dimensions`, which this re-exports so that importers need one module.
What the harness does with the feed, and which ceilings it holds it to, is next door in
`measure_scale`.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from _scale_dimensions import (
    CANARY_AGENCY,
    CANARY_HEADSIGN,
    CANARY_LOCATION_GROUP,
    CANARY_TRIP,
    EXCEPTIONS,
    HEADSIGN,
    LONG_TRIP_STOPS,
    LONG_TRIPS,
    PATHWAY_PLATFORMS,
    SERVICES,
    SHAPE_ORIGIN,
    SHAPE_POINTS,
    SHAPES,
    STOPS,
    TRIPS_PER_BLOCK,
    TRIPS_PER_SERVICE,
    YEARS,
)

__all__ = [
    "CANARY_AGENCY",
    "CANARY_HEADSIGN",
    "CANARY_LOCATION_GROUP",
    "CANARY_TRIP",
    "EXCEPTIONS",
    "HEADSIGN",
    "LONG_TRIPS",
    "LONG_TRIP_STOPS",
    "PATHWAY_PLATFORMS",
    "SERVICES",
    "SHAPES",
    "SHAPE_ORIGIN",
    "SHAPE_POINTS",
    "STOPS",
    "TRIPS_PER_BLOCK",
    "TRIPS_PER_SERVICE",
    "YEARS",
    "build_feed",
]


def _walked(step: int) -> int:
    """The stop index `step` hops along the list, turning round at each end instead of wrapping.

    A wrap puts one 28 km hop into a trip, which is reported as fast travel, and a reported
    pair ends the span scan. The first version of the long trips wrapped and so measured the
    early exit rather than the walk they were written for. The short trips wrapped too, which
    is why this feed used to report thousands of travel-speed notices, and why the check in
    `run` that no such notice exists could not have been written against it.
    """
    period = 2 * (STOPS - 1)
    position = step % period
    return position if position < STOPS else period - position


def _calendar() -> str:
    header = (
        "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
    )
    rows = []
    for index in range(SERVICES):
        # A single active weekday, so the service expands to one run per week over
        # the whole range rather than one long run.
        pattern = ["0"] * 7
        pattern[index % 7] = "1"
        start = 2026 - YEARS
        rows.append(f"S{index},{','.join(pattern)},{start}0101,{2026 + YEARS}1231\n")
    # A second family, one service per weekday, carrying *no* calendar_dates exceptions. The
    # block trips run these. Reasoning from the weekly pattern alone was not enough: the 40,000
    # exceptions below add about a hundred dates to every S service, and two S services with
    # different weekdays share added dates constantly, which had a fully-overlapping block
    # reporting 71,994 notices on the first run after the blocks were made to overlap. A service
    # nothing adds to is disjoint from its siblings by construction.
    for index in range(TRIPS_PER_BLOCK):
        pattern = ["0"] * 7
        pattern[index] = "1"
        start = 2026 - YEARS
        rows.append(f"BS{index},{','.join(pattern)},{start}0101,{2026 + YEARS}1231\n")
    return header + "".join(rows)


def _calendar_dates() -> str:
    # Descending, which is the order that made insertion quadratic, and spread
    # across services, which is the shape that defeated a per-service buffer cap.
    rows = []
    for offset in range(EXCEPTIONS, 0, -1):
        service = f"S{offset % SERVICES}"
        day = 1 + (offset % 28)
        month = 1 + (offset % 12)
        year = 2030 + (offset % 5)
        rows.append(f"{service},{year}{month:02d}{day:02d},1\n")
    return "service_id,date,exception_type\n" + "".join(rows)


def _long_trips() -> str:
    # One block each, deliberately. The long trips all start within a minute of each other and
    # run for nearly seven hours, so putting them in one block made every one of their 190 pairs
    # overlap: the check in `run` caught that on the first run after block ids were added. The
    # block scan's load is the 24,000 short trips; these are here for the travel-speed span walk.
    return "".join(
        f"R{index % 20},S{index % SERVICES},L{index},LB{index},"
        f"{CANARY_HEADSIGN if f'L{index}' == CANARY_TRIP else HEADSIGN},H{index % SHAPES}\n"
        for index in range(LONG_TRIPS)
    )


def _trips() -> str:
    """Half the trips in blocks, half not, and the two halves run different service families.

    The block half is on the exception-free `BS` services so a fully-scanned block stays silent.
    The other half keeps the `S` services, which is what holds the trip-to-service join at
    400-service cardinality: putting *every* trip on seven services would have quietly shrunk a
    dimension this feed exists to stress while fixing a different one.
    """
    rows = []
    for index in range(SERVICES * TRIPS_PER_SERVICE):
        if index % 2:
            rows.append(
                f"R{index % 20},S{index % SERVICES},T{index},,{HEADSIGN},H{index % SHAPES}\n"
            )
            continue
        position = index // 2
        service = f"BS{position % TRIPS_PER_BLOCK}"
        block = f"B{position // TRIPS_PER_BLOCK}"
        rows.append(f"R{index % 20},{service},T{index},{block},{HEADSIGN},H{index % SHAPES}\n")
    return (
        "route_id,service_id,trip_id,block_id,trip_headsign,shape_id\n"
        + "".join(rows)
        + _long_trips()
    )


def _shapes() -> str:
    """`SHAPES` shapes of `SHAPE_POINTS` points each, each a short diagonal run.

    Increasing in both latitude and longitude so the points are distinct and the shape's own
    distance checks stay quiet, and far from every stop so the matcher takes its expensive path.
    """
    rows = []
    for shape in range(SHAPES):
        for point in range(SHAPE_POINTS):
            latitude = SHAPE_ORIGIN[0] + shape * 0.01 + point * 0.0001
            longitude = SHAPE_ORIGIN[1] + point * 0.0001
            rows.append(f"H{shape},{latitude:.6f},{longitude:.6f},{point + 1}\n")
    return "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n" + "".join(rows)


def _frequencies() -> str:
    # One row per trip, each expanding to many trips, so the frequency join is
    # exercised at full trips.txt cardinality.
    rows = [f"T{index},06:00:00,22:00:00,600\n" for index in range(SERVICES * TRIPS_PER_SERVICE)]
    return "trip_id,start_time,end_time,headway_secs\n" + "".join(rows)


def _pathway_station() -> str:
    """A station of platforms wired to two entrances, and one platform wired to neither.

    Without a `pathways.txt` at all, `PathwayReachableLocationValidator` does nothing and the run
    covers none of it. That is the same trap as the block ids, the headsign and the shapes, and this
    is the fourth entry in that list.

    The station is separate from the `P*` stops the trips visit, so it changes neither the
    travel-speed dimensions nor the shape-matching canary's count: no `stop_times.txt` row names
    these, and the stop-to-shape walk only reaches stops a trip visits.

    One platform is left unconnected on purpose. A station where everything is reachable would be
    silent, and silence is what a working scan and an absent one look like alike.

    A **generic node** stands between the entrances and the platforms, so every platform is two hops
    from an entrance rather than one. A review found the first version of this station could not tell
    a working traversal from one that stopped after the first layer, because every platform was
    directly adjacent to an entrance.
    """
    rows = [
        "PWST,Pathway Station,41.5,-73.5,1,\n",
        "PWEN0,Entrance North,41.5001,-73.5,2,PWST\n",
        "PWEN1,Entrance South,41.5002,-73.5,2,PWST\n",
        "PWND,Concourse,41.5003,-73.5,3,PWST\n",
    ]
    for index in range(PATHWAY_PLATFORMS):
        rows.append(f"PWP{index},Pathway Platform {index},41.51,-73.5{index:03d},0,PWST\n")
    return "".join(rows)


def _pathways() -> str:
    """Both entrances to the concourse, and the concourse to every platform but the last.

    Half the platform rows are written **platform-first** and half concourse-first. Both are
    bidirectional and so mean the same thing, and the same review found that a station whose rows all
    ran entrance-first could not detect the loss of the bidirectional test in the reverse-direction
    half of the traversal: the forward search never needed to follow a row backwards.
    """
    rows = [
        "PW1,PWEN0,PWND,1,1\n",
        # Written the other way round, so reaching the concourse from the south entrance needs the
        # reverse-direction traversal to honour `is_bidirectional`.
        "PW2,PWND,PWEN1,1,1\n",
    ]
    identifier = 2
    for index in range(PATHWAY_PLATFORMS - 1):
        identifier += 1
        if index % 2:
            rows.append(f"PW{identifier},PWND,PWP{index},1,1\n")
        else:
            rows.append(f"PW{identifier},PWP{index},PWND,1,1\n")
    return "pathway_id,from_stop_id,to_stop_id,pathway_mode,is_bidirectional\n" + "".join(rows)


def _attributions() -> str:
    """One attribution whose agency_id names no agency.

    A feed where every reference resolves is silent on foreign_key_violation, and silence is what a
    working check and an absent one look like alike: the same trap as the block ids, the headsign,
    the shapes and the pathways. This is the fifth.

    attributions.txt is chosen because almost nothing else reads it, so the planted violation does
    not move another rule's count. is_producer is set to keep attribution_without_role quiet.
    """
    return (
        f"attribution_id,organization_name,agency_id,is_producer\nAT1,Acme Data,{CANARY_AGENCY},1\n"
    )


def build_feed(path: Path) -> None:
    stops = (
        "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
        + "".join(
            f"P{index},Stop {index},40.{index:03d},-74.{index:03d},,\n" for index in range(STOPS)
        )
        + _pathway_station()
    )
    routes = "route_id,agency_id,route_short_name,route_long_name,route_type\n" + "".join(
        f"R{index},1,{index},Route {index},3\n" for index in range(20)
    )
    stop_times = ["trip_id,arrival_time,departure_time,stop_id,stop_sequence,location_group_id\n"]
    for index in range(SERVICES * TRIPS_PER_SERVICE):
        # Every trip runs 08:00 to 08:03, so all seven trips of a block overlap and the block
        # scan walks the whole triangle instead of breaking on its first comparison. See
        # TRIPS_PER_BLOCK for why a fully-overlapping block still reports nothing.
        for sequence in range(4):
            stop = f"P{_walked(index + sequence)}"
            group = CANARY_LOCATION_GROUP if (index, sequence) == (0, 0) else ""
            stop_times.append(
                f"T{index},08:0{sequence}:00,08:0{sequence}:00,{stop},{sequence + 1},{group}\n"
            )
    for trip in range(LONG_TRIPS):
        for sequence in range(LONG_TRIP_STOPS):
            # A minute a hop over about 140 m, which is 8 km/h: under every threshold, so no
            # pair is ever reported and the scan walks every pair it can.
            moment = 5 * 3600 + trip + sequence * 60
            clock = f"{moment // 3600:02d}:{moment % 3600 // 60:02d}:{moment % 60:02d}"
            stop_times.append(f"L{trip},{clock},{clock},P{_walked(sequence)},{sequence + 1},\n")
    tables = {
        "agency.txt": (
            "agency_id,agency_name,agency_url,agency_timezone\n"
            "1,Acme Transit,https://example.com,America/New_York\n"
        ),
        "stops.txt": stops,
        "routes.txt": routes,
        "trips.txt": _trips(),
        "stop_times.txt": "".join(stop_times),
        "calendar.txt": _calendar(),
        "calendar_dates.txt": _calendar_dates(),
        "shapes.txt": _shapes(),
        "pathways.txt": _pathways(),
        "attributions.txt": _attributions(),
        "frequencies.txt": _frequencies(),
        "feed_info.txt": (
            "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date\n"
            "Pub,https://example.com,en,20260101,20261231\n"
        ),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in tables.items():
            archive.writestr(name, body)
