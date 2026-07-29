"""Everything a rule needs that is not in the feed.

Upstream injects these through Dagger as DateForValidation and CountryCode. Both
are read by rules rather than by the engine, which is why they live here rather
than being threaded through the pipeline.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Context:
    """The validation date and the country code the -c flag carries."""

    date: datetime.date
    country_code: str
