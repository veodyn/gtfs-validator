"""Reading Gson's way: string coercion and the duplicate-key rejection."""

from __future__ import annotations

import json
from typing import Any

from gtfs_validator.geojson.constants import DuplicateKey, UnreadableGeoJson
from gtfs_validator.javatext import double_string


def _as_string(value: Any) -> str:
    """Gson's JsonPrimitive.getAsString, which upstream calls before comparing.

    Lowercase booleans, because Java prints `true` where Python prints `True`, and
    the value reaches the report: measured, a root `type` of JSON `true` draws
    `geoJsonType: "true"` and a message containing `true`.

    Gson throws on a structured value or null, and upstream's bare catch then drops
    the whole file, so those raise here rather than producing a notice.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        # A JSON number reaches the report as a Java double, so 7 renders "7.0" and not "7".
        # Measured on a feature whose id is 7: the jar reports featureId "7.0" for
        # unsupported_geometry_type and entityId "7.0" for point_near_origin. `str` gave "7",
        # and no probe had compared the two until a point_near notice carried the id.
        return double_string(value)
    raise UnreadableGeoJson(f"cannot read {type(value).__name__} as a string")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    """object_pairs_hook: the only place a duplicate key is still visible.

    json.loads keeps the last value, so the fact is gone before any check can run.
    Upstream registers a custom Gson adapter for the same reason and says so in a
    comment on the registration.

    Raises on the first duplicate this hook sees, which is **not** always the key
    Gson reports. The hook fires bottom-up, after every child value is decoded,
    while Gson reads top-down and throws on the first duplicate in document order.
    So for `{"type":..., "type":{"x":1,"x":2}, ...}` the jar reports `type` and this
    reports `x`.

    That divergence is deliberate, and it replaced a worse one. A previous version
    tracked the shallowest duplicate per object so the outer key would win, and it
    keyed that metadata by the id of each decoded dict. A feature lives inside the
    `features` **array**, and arrays get no hook, so the metadata never reached the
    root and a duplicate key inside a feature was silently dropped: no notice at
    all, on the likeliest real-world shape. Reporting the notice with the inner key
    is strictly better than not reporting it.

    Getting both right needs the source position of each duplicate, which this hook
    does not receive. See divergence 7.
    """
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise DuplicateKey(key)
        seen.add(key)
    return dict(pairs)


def decode(text: str) -> Any:
    """Decode with Python's own number parsing, deliberately.

    A review asked for the raw lexeme to be kept, on the grounds that Gson's
    getAsString returns the original token, so a root `type` of `1e3` would report
    as `"1e3"`. Measured: the jar reports `"1000.0"`. Gson parses the number and
    formats it back, which is what `str(float(...))` already does, so keeping the
    lexeme would have introduced the very divergence it was meant to prevent.
    """
    return json.loads(text, object_pairs_hook=_reject_duplicates)
