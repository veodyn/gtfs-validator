"""Every dimension the scale feed is sized on, and why each number is what it is.

Split from the builders when the two together passed the file-size limit. This is the half worth
reading: each constant here exists because some rule was once quadratic in it, or because a rule did
nothing at all until the feed carried it, and the reason is written next to the number.

Four rules have been in the second category, certified "within ceilings" without having run: the
block scan, the headsign scan, the stop-to-shape matcher and the pathway traversal. Each is named
below beside the dimension that fixed it.
"""

from __future__ import annotations

SERVICES = 400
YEARS = 12
# Left at 60. The first attempt at closing the real-feed gap raised this tenfold, on the theory that
# stop_times rows drive the cost. The corpus says otherwise: 648-AT has 5,784,756 stop_times rows and
# finishes and matches, while 767-CZ has 3.5x fewer rows and runs for tens of minutes. What separates
# them is shapes, so the shape dimensions below are where the tenfold went.
TRIPS_PER_SERVICE = 60
EXCEPTIONS = 40_000
STOPS = 200
# A handful of long trips as well as many short ones. StopTimeTravelSpeedValidator's span scan
# is quadratic in a trip's stop times, as upstream's is, and 24,000 four-stop trips never show
# it: the worst case is a long trip that reports *nothing*, since a reported pair ends the
# scan. These are built to be slow everywhere so the whole triangle runs, and distinct from
# each other so the fingerprint cannot collapse them into one group.
LONG_TRIPS = 20
LONG_TRIP_STOPS = 400
# Every trip gets a block id, in runs of this many. BlockTripsWithOverlappingStopTimesValidator
# is quadratic in a block's trips and reads each one's stop times, so a feed with no block ids
# leaves it doing nothing at all: it was added to this harness only after the same feed had been
# certified "within ceilings" for two rules that never ran on it.
#
# Seven, and the trips of a block deliberately run at the *same* time. The first version
# staggered them an hour apart, which meant each trip's very first comparison found a
# non-overlapping successor and broke, so the scan was linear and the service-intersection cache
# was never consulted at all: a review caught the harness claiming a quadratic path it did not
# have. Overlapping in time keeps the inner loop running to the end of the block; seven is
# because trip `index` runs service `S{index % SERVICES}`, whose only active weekday is
# `index % 7`, so seven consecutive trips hold seven distinct weekdays and no two of them ever
# run on the same day. That is what keeps a fully-scanned block silent.
TRIPS_PER_BLOCK = 7
# Every trip carries a headsign, because TripHeadsignValidator reads the stop times of every trip
# that has one and does nothing at all for a trip that does not. A feed with the column absent
# left it in the same position the block scan was in before block ids were added: certified
# "within ceilings" without having run.
#
# The value matters twice over. It must match no stop name, since a notice is not the point here,
# and no trip may begin and end at the same stop, since that ends the scan for the whole feed
# rather than for the trip. Neither is an accident of this string: `_walked` turns round at each
# end instead of wrapping, so a four-hop walk never returns to where it started, and the stops
# are named `Stop 0` through `Stop 199`.
HEADSIGN = "Terminus"
# The last trip in trips.txt gets a headsign that *does* match one of its intermediate stops, so
# it must draw exactly one notice. This is a canary rather than a fixture: silence cannot show
# that this scan ran, because the thing that ends it early is a circular trip, which reports
# nothing either. A notice from the last trip in the file is direct evidence that the loop reached
# the end.
#
# `Stop 199` names the stop at the far end of the walk, and it is the far end that makes the count
# exactly one. `_walked` turns round rather than wrapping, so a 400-hop trip visits every other
# stop *twice*: the first attempt at this canary named `Stop 5` and drew two notices, at
# stop_sequence 6 and 394. Only the turnaround stop is visited once, at stop_sequence 200.
CANARY_HEADSIGN = f"Stop {STOPS - 1}"
CANARY_TRIP = f"L{LONG_TRIPS - 1}"
# Shapes, and a shape_id on every trip. Without these ShapeToStopMatchingValidator does nothing at
# all: the feed carried no shapes.txt, so the four stop-to-shape codes would have been certified
# "within ceilings" without running, which is the third time this harness has been in that
# position. See the block-id and headsign comments above for the first two.
#
# The dimensions are the ones the matcher's cost is linear in. It scans every segment of the shape
# for every stop of every *distinct* trip pattern, as upstream does, and when a stop has no
# candidate within the threshold it scans them all a second time to find the single closest point.
#
# **Not every trip**, and a review corrected this comment for claiming so. `processed_trip_hashes`
# collapses trips whose stop pattern and distances match, and this feed's short trips repeat: of
# 24,020 trips and 104,000 stop-time rows, **4,000 patterns survive the fingerprint (200 per shape)
# carrying 23,920 rows**, counted by hashing the generated input directly. The collapse is
# upstream's behaviour and a real feed of many trips over few shapes has it too, so the feed is
# right and the arithmetic to extrapolate from is *patterns* times stops times segments, not trips.
#
# Measured at 1.85 microseconds per segment per stop. 200 points rather than a token 60, which is
# both closer to a real agency shape and what makes the geometry the largest single item in the run
# instead of a rounding error: the first version at 60 points added about 6s of a 20s run.
#
# **Five times the points it used to have, and the corpus is why.** At 200 points the geometry was
# the largest single item in a 31s run and still nowhere near a real feed: `767-CZ` carries 7,786
# shapes averaging 443 points, 3,453,261 points in all, against this feed's 4,000. Putting that feed
# through the arithmetic above, 80,954 patterns times about 20 stops times 442 segments at 1.85
# microseconds, predicts about 22 minutes of geometry alone, and it did run for tens of minutes. The
# model was right; the feed was not exercising it.
#
# 1,000 rather than 443, because points per shape is what the cost is linear in and a round number
# that overshoots the real mean is the honest way to leave headroom. 4,000 patterns times 4 stops
# times 999 segments is about 16 million operations, roughly 30s of geometry, which keeps this a
# guard that runs on every change rather than one nobody runs. The tail beyond that belongs to
# `measure_real_scale.py` and an actual feed.
SHAPES = 20
SHAPE_POINTS = 1000
# The shape runs nowhere near the stops, which are spread over 0.2 degrees. Every stop is therefore
# too far from it, which is the expensive path rather than the cheap one: a stop with no candidate
# costs two full scans instead of one, and the notice is deduplicated per (shape, stop) so the
# output stays bounded at SHAPES * STOPS however many trips there are.
SHAPE_ORIGIN = (41.0, -72.0)
# A station whose platforms have pathways, because `PathwayReachableLocationValidator` does nothing
# for a feed with no pathways.txt and the run would cover none of it. Its cost is linear in stops and
# in pathways rather than quadratic in either, so this is sized to make the rule *run* and to be
# checkable, not to stress it: 100 platforms and 198 pathways, with one platform deliberately
# unconnected so the rule reports exactly once. See `_pathway_station`.
PATHWAY_PLATFORMS = 100
# The attributions.txt row whose agency_id names nothing, so foreign_key_violation reports exactly
# once on a feed where every other one of its fifty references resolves. attributions.txt is chosen
# because almost nothing else reads it, so the planted violation does not move another rule's count.
CANARY_AGENCY = "GHOSTAGENCY"
# The one stop_times.txt row whose location_group_id names nothing, since location_groups.txt is
# absent and optional. The second half of the foreign key canary: the attribution above proves the
# rule ran at all, and this proves it ran over the largest table in the feed, which is the anti-join
# whose cost the elapsed time is supposed to cover.
CANARY_LOCATION_GROUP = "GHOSTGROUP"
