"""Builders for the locations.geojson parser tests.

One definition rather than one per module. The parser's tests are split in two, structural
notices and the coordinate scan, and both need the same four helpers; duplicating them was fine
until each half grew past the file-size limit on its own.
"""

from __future__ import annotations

import json

from gtfs_validator.geojson import parse
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.table_status import TableLoad

# Deliberately not near (0, 0). A ring within one degree of the origin draws point_near_origin
# for every one of its points, which is upstream's behaviour and would otherwise be mixed into
# every test that uses this default. The origin and pole checks build their own rings.
RING = [[[-73.0, 40.0], [-73.0, 40.1], [-72.9, 40.1], [-72.9, 40.0], [-73.0, 40.0]]]


def feature(**overrides):
    row = {
        "id": "L1",
        "type": "Feature",
        "properties": {},
        "geometry": {"type": "Polygon", "coordinates": RING},
    }
    row.update(overrides)
    return row


def collection(*features, **extra):
    root = {"type": "FeatureCollection", "features": list(features)}
    root.update(extra)
    return json.dumps(root)


def run(text):
    notices = NoticeContainer()
    load = TableLoad()
    rows = parse(text, notices, load)
    found = [n for group in notices.grouped().values() for n in group]
    return rows, found, load


def contexts(found, code):
    return [n.context for n in found if n.code == code]
