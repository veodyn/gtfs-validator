"""The CSV half of `point_near_pole`, from the generated per-table lat/lon validators.

The other half is `GeoJsonFileLoader.validateCoordinates`, in `geojson/features.py`. This module
covers `LatLonValidatorGenerator`'s output, which is a SingleEntityValidator per table carrying a
lat/lon pair: stops.txt and shapes.txt at the pin.

It is a file rule rather than an entity rule only because the registry holds one spec per code and
this one code comes from two tables. `entity_rows` keeps the SingleEntityValidator semantics: a row
is checked as it loads, so it is still checked in a table whose load later fails.
"""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.lat_lon import LAT_LON_TABLES, suspicious_rows
from gtfs_validator.rules.registry import file_rule

CODE = "point_near_pole"


@file_rule(code=CODE, severity=Severity.ERROR)
def check(feed, ctx: Context) -> Iterator[Notice]:
    for filename, latitude_field, longitude_field, key_field in LAT_LON_TABLES:
        for code, context in suspicious_rows(
            feed, filename, latitude_field, longitude_field, key_field
        ):
            if code == CODE:
                yield Notice(CODE, Severity.ERROR, context)
