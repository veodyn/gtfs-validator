"""Context-value renderers whose Java form is not str(value).

Gson serialises a few notice field types through a registered adapter rather
than reflectively, so the report carries the adapter's output. Reproducing that
is part of parity level C: the value is what a consumer reads.
"""

from __future__ import annotations


def html_color(rgb: int) -> str:
    """GtfsColor.toHtmlColor, which is String.format("#%06X", rgb).

    Takes the packed integer the store holds, not the feed's text: COLOR is an
    INTEGER column, so "ffffff" has already become 16777215 by the time a rule
    sees it. Rendering is uppercase, six digits, leading hash, so a feed
    spelling a color in lowercase is reported in uppercase either way.
    """
    return f"#{rgb:06X}"


def rec601_luma(rgb: int) -> int:
    """GtfsColor.rec601Luma: (int)(0.30r + 0.59g + 0.11b), truncated.

    Java casts a double to int, which truncates towards zero rather than
    rounding. int() does the same for a non-negative value, and a luma is never
    negative.
    """
    red = (rgb & 0xFF0000) >> 16
    green = (rgb & 0x00FF00) >> 8
    blue = rgb & 0x0000FF
    return int(0.30 * red + 0.59 * green + 0.11 * blue)


def hhmmss(seconds: int) -> str:
    """GtfsTime.toHHMMSS. Hours run past 24, so this is not strftime."""
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
