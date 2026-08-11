"""Pure-Python validator for the canonical GTFS rule set."""

# Derived rather than repeated. This was a third hardcoded copy of the version
# that nothing read, so nothing would have failed if it had drifted.
from gtfs_validator.version import VERSION as __version__

__all__ = ["__version__"]
