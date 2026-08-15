"""Pure-Python validator for the canonical GTFS rule set."""

# Derived rather than repeated. This was a third hardcoded copy of the version
# that nothing read, so nothing would have failed if it had drifted.
from gtfs_validator.reading import LoadedFeed, RawView, open_feed_view, open_raw_view
from gtfs_validator.rules.feedview import DependencyFailed
from gtfs_validator.version import VERSION as __version__

# The loader is exported on purpose, and the promise is narrow: these names, and
# the `FeedView` they hand back, may not change shape without a major version.
# `FeedView` is what all 135 rule modules already read a feed through, so it is
# the least likely thing here to move. Nothing else in this package is public;
# a caller reaching past these is on its own.
#
# `DependencyFailed` is here because it is the exception every read through a
# `FeedView` can raise, so a caller that wants to fail with an error type of its
# own has to be able to name it. It was reachable before and not promised, which
# left the one caller doing it importing from `rules.feedview` under a comment
# saying it was on its own.
#
# `open_raw_view` and `RawView` are the untyped surface beside the typed one.
# `reading` says why a lenient reader cannot be built out of the strict path.
__all__ = [
    "DependencyFailed",
    "LoadedFeed",
    "RawView",
    "__version__",
    "open_feed_view",
    "open_raw_view",
]
