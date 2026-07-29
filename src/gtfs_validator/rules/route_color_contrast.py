"""RouteColorContrastValidator: a luma difference below 72 is too little contrast."""

from __future__ import annotations

from collections.abc import Iterator

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.render import html_color, rec601_luma
from gtfs_validator.rules.registry import rule

MAX_ROUTE_COLOR_LUMA_DIFFERENCE = 72


@rule(code="route_color_contrast", severity=Severity.WARNING, filename="routes.txt")
def check(row: dict, ctx: Context) -> Iterator[Notice]:
    color = row.get("route_color")
    text_color = row.get("route_text_color")
    if color is None or text_color is None:
        return
    if abs(rec601_luma(color) - rec601_luma(text_color)) < MAX_ROUTE_COLOR_LUMA_DIFFERENCE:
        yield Notice(
            "route_color_contrast",
            Severity.WARNING,
            {
                "routeId": row["route_id"],
                "csvRowNumber": row["_row_number"],
                "routeColor": html_color(color),
                "routeTextColor": html_color(text_color),
            },
        )
