"""Pure-Python validator for the canonical GTFS rule set."""

# Derived rather than repeated. This was a third hardcoded copy of the version
# that nothing read, so nothing would have failed if it had drifted.
from gtfs_validator.reading import LoadedFeed, open_feed_view
from gtfs_validator.version import VERSION as __version__

# The loader is exported on purpose, and the promise is narrow: these names, and
# the `FeedView` they hand back, may not change shape without a major version.
# `FeedView` is what all 135 rule modules already read a feed through, so it is
# the least likely thing here to move. Nothing else in this package is public;
# a caller reaching past these is on its own.
__all__ = ["LoadedFeed", "__version__", "open_feed_view"]
