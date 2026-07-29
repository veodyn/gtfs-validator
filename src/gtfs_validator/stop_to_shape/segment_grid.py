"""A prune-only spatial index over one shape's segments.

Answers one question conservatively: which segment indices might lie within a given
distance of a point. False positives are fine and are filtered by the caller's exact
arithmetic; a false negative would change which notices fire, so every bound here is
inflated, never trimmed. The caller's loops and floats are untouched: this module never
computes a distance that reaches a report.

Cells are degree-quantized lat/lng boxes, with the longitude cell widened by the
shape's worst-case latitude so cells stay roughly square in metres. Each segment is
inserted into every cell its own bounding box overlaps, **uninflated**; a query widens
its own box by its own threshold instead. Inflating at query time rather than insert
time is what lets the cells be small: with segment-side inflation a cell much smaller
than the 400 m worst-case threshold puts every segment in dozens of cells, and small
cells are the whole point, because the candidate count per query is the cell density
times the box area. It also means a 100 m query reads a 100 m box rather than paying
the large-station 400 m everywhere.

A query reads the cells its threshold box overlaps, or walks outward ring by ring for
the closest-point search, with a per-ring lower bound that tells the caller when its
running best cannot be beaten.

Poles and the antimeridian get the safe answer rather than a clever one: a shape that
reaches past 85 degrees of latitude or spans more than 120 degrees of longitude
disables the grid, and a disabled grid answers `None`, which the caller reads as "scan
everything", exactly the loop the matcher ran before this module existed.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

# Metres per degree of latitude is 111,194.9 on this sphere (R * pi / 180). Dividing by
# the floor over-states a distance converted to degrees, which is the safe direction for
# a query box; multiplying by it under-states a cell bound, safe again.
_METERS_PER_DEGREE_FLOOR = 110_000.0
# Under the sphere's true radius of 6,371,010 m, so a bound built on it under-states.
_RADIUS_FLOOR_METERS = 6_370_000.0
_POLE_LIMIT_DEGREES = 85.0
_LON_SPAN_LIMIT_DEGREES = 120.0
# Cell sizing. The finer the cells, the fewer false-positive candidates a query
# returns; the floor keeps a city-block shape from building thousands of cells for
# nothing, and the per-axis cap keeps a country-spanning shape's insertion bounded: a
# segment lands in the cells along its own length, so entries scale with path length
# over cell size.
_MAX_CELLS_PER_AXIS = 1_024
_MIN_CELL_DEGREES = 0.002
# A segment whose box covers more cells than this marks the grid degenerate: some
# geometry is stranger than the index is worth.
_MAX_CELLS_PER_SEGMENT = 4_096
# The longest segment, per axis in degrees, the grid will index. Real consecutive
# shape points are metres to a few kilometres apart; a single segment spanning more
# than a degree is degenerate data, and it is also where the arc-bulge inflation and
# the cosine floor would stop being cheap, so such a shape scans instead.
_MAX_SEGMENT_SPAN = 1.0


class SegmentGrid:
    """The index for one shape, built from its vertices in sequence order."""

    def __init__(self, latlons: list[tuple[float, float]]) -> None:
        self._disabled = True
        self._cells: dict[tuple[int, int], list[int]] = {}
        if len(latlons) < 2:
            return
        lats = [lat for lat, _ in latlons]
        lons = [lon for _, lon in latlons]
        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)
        if max(abs(min_lat), abs(max_lat)) > _POLE_LIMIT_DEGREES:
            return
        if max_lon - min_lon > _LON_SPAN_LIMIT_DEGREES:
            return
        # cos beyond the extreme latitude by the largest bulge a kept segment can
        # add (see below), so every point of an arc and of a query box is covered.
        self._cos_floor = math.cos(
            math.radians(min(89.0, max(abs(min_lat), abs(max_lat)) + 2.0 * _MAX_SEGMENT_SPAN + 0.1))
        )
        span = max(max_lat - min_lat, (max_lon - min_lon) * self._cos_floor)
        self._lat_cell = max(_MIN_CELL_DEGREES, span / _MAX_CELLS_PER_AXIS)
        self._lon_cell = self._lat_cell / self._cos_floor
        for index in range(len(latlons) - 1):
            (lat_a, lon_a), (lat_b, lon_b) = latlons[index], latlons[index + 1]
            lat_span = abs(lat_a - lat_b)
            lon_span = abs(lon_a - lon_b)
            # A great-circle segment is an arc, not the box between its endpoints: a
            # long east-west segment at high latitude bows poleward of both. A review
            # measured a stop nanometres from such an arc that the endpoint box
            # pruned away. Every arc point lies within the segment's own angular
            # length of either endpoint, so inflating the box by that length covers
            # the bulge; a segment long enough to make that expensive is degenerate
            # shape data and disables the grid instead.
            if lat_span > _MAX_SEGMENT_SPAN or lon_span > _MAX_SEGMENT_SPAN:
                self._cells.clear()
                return
            bulge = lat_span + lon_span
            row_lo = self._row(min(lat_a, lat_b) - bulge)
            row_hi = self._row(max(lat_a, lat_b) + bulge)
            col_lo = self._col(min(lon_a, lon_b) - bulge / self._cos_floor)
            col_hi = self._col(max(lon_a, lon_b) + bulge / self._cos_floor)
            if (row_hi - row_lo + 1) * (col_hi - col_lo + 1) > _MAX_CELLS_PER_SEGMENT:
                self._cells.clear()
                return
            for row in range(row_lo, row_hi + 1):
                for col in range(col_lo, col_hi + 1):
                    self._cells.setdefault((row, col), []).append(index)
        rows = [row for row, _ in self._cells]
        cols = [col for _, col in self._cells]
        self._row_lo, self._row_hi = min(rows), max(rows)
        self._col_lo, self._col_hi = min(cols), max(cols)
        self._disabled = False

    @property
    def enabled(self) -> bool:
        """False when the geometry defeated the index; the caller then scans everything."""
        return not self._disabled

    def _row(self, lat: float) -> int:
        return math.floor(lat / self._lat_cell)

    def _col(self, lon: float) -> int:
        return math.floor(lon / self._lon_cell)

    def candidates(self, lat: float, lon: float, max_distance_meters: float) -> list[int] | None:
        """Sorted superset of the segments within the threshold of the point, or None.

        None means the grid is disabled and the caller must scan every segment. An
        empty list is a real answer: no segment can be within the threshold. The
        query box is the threshold widened by 5% and one extra cell of slack, floored
        in the conversion, so every direction over-covers.
        """
        if self._disabled:
            return None
        inflate_lat = max_distance_meters * 1.05 / _METERS_PER_DEGREE_FLOOR
        inflate_lon = inflate_lat / self._cos_floor
        row_lo = max(self._row(lat - inflate_lat), self._row_lo)
        row_hi = min(self._row(lat + inflate_lat), self._row_hi)
        # A query box crossing the antimeridian also queries itself shifted by a full
        # turn: the shape's cells sit at the longitudes the feed wrote, so a stop at
        # -179.9997 must reach a shape stored at +179.9997. A review measured that
        # without this the stop lost its 43 candidates and its notice with them. The
        # shape itself cannot straddle the seam while the grid is enabled, since a
        # straddling shape spans over 120 degrees of raw longitude and is disabled.
        spans = [(lon - inflate_lon, lon + inflate_lon)]
        if lon - inflate_lon < -180.0:
            spans.append((lon - inflate_lon + 360.0, lon + inflate_lon + 360.0))
        if lon + inflate_lon > 180.0:
            spans.append((lon - inflate_lon - 360.0, lon + inflate_lon - 360.0))
        found: set[int] = set()
        for span_lo, span_hi in spans:
            col_lo = max(self._col(span_lo), self._col_lo)
            col_hi = min(self._col(span_hi), self._col_hi)
            for row in range(row_lo, row_hi + 1):
                for col in range(col_lo, col_hi + 1):
                    segments = self._cells.get((row, col))
                    if segments is not None:
                        found.update(segments)
        return sorted(found)

    def cells_by_bound(self, lat: float, lon: float) -> Iterator[tuple[list[int], float]]:
        """Every occupied cell's segments with a lower bound in metres, nearest first.

        The bound under-states the distance from the query point to anything in its
        cell, so a caller holding an exact best distance smaller than the next cell's
        bound can stop; a bound *equal* to the best must still be consumed, since a
        tie is resolved by segment index, not by cell. A segment spanning several
        cells appears once per cell.

        The bound is the haversine at the corner of the cell nearest the query in
        degree space, with the latitude term exact and the longitude term floored by
        the grid's own worst-case cosine, so it cannot exceed the true distance to
        any point of the cell. Longitude differences are folded across the
        antimeridian before use.
        """
        if self._disabled:
            return
        sin_half = math.sin
        half_lat = math.radians(self._lat_cell) / 2.0
        cos_query = math.cos(math.radians(lat))
        bounded: list[tuple[float, tuple[int, int]]] = []
        for (row, col), _segments in self._cells.items():
            # Nearest point of the cell in degree space: clamp the query into it.
            cell_lat = _clamp(lat, row * self._lat_cell, (row + 1) * self._lat_cell)
            cell_lon = _clamp(lon, col * self._lon_cell, (col + 1) * self._lon_cell)
            delta_lat = math.radians(abs(lat - cell_lat))
            delta_lon = math.radians(min(abs(lon - cell_lon), 360.0 - abs(lon - cell_lon)))
            haversine = (
                sin_half(delta_lat / 2.0) ** 2
                + cos_query * self._cos_floor * sin_half(delta_lon / 2.0) ** 2
            )
            distance = 2.0 * math.asin(min(1.0, math.sqrt(haversine))) * _RADIUS_FLOOR_METERS
            # One cell of slack for the latitude range the cosine floor already
            # covers imperfectly at the cell's own edge, then never negative.
            bounded.append((max(0.0, distance - half_lat * _RADIUS_FLOOR_METERS), (row, col)))
        bounded.sort()
        for bound, key in bounded:
            yield self._cells[key], bound


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value
