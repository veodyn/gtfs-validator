"""The typed stop_times rows the two flex-window cohorts share.

`PickupDropOffWindowValidator` reads the two window columns and the two time columns;
`StopTimesRecordValidator` reads the two window columns and the two type columns. The two
window columns are the whole overlap, and they are what this builder spells, so the row
builder and the probes' times live here rather than twice. One definition also keeps the two
modules from drifting on the detail that decides several of their cases: an absent field is
*omitted*, not set to None, so an explicit midnight stays distinguishable from an absence.

The window column names come from the production constants rather than being spelled again
here, so a rename cannot leave the tests agreeing with themselves against a column no feed
has. The literal spellings are pinned once, in the header-gate test.
"""

from __future__ import annotations

from gtfs_validator.rules._shared.windows import END_WINDOW, START_WINDOW

# The probes' times, in the seconds the store holds.
T0700, T0800, T0830, T0900 = 25200, 28800, 30600, 32400
T1000, T1200 = 36000, 43200
T2500, T2530, T2600 = 90000, 91800, 93600

# GtfsPickupDropOff. An unset column reads as REGULAR rather than as an absence.
MUST_PHONE = 2
REGULAR = 0

STOP_TIMES = "stop_times.txt"


def stop_time(number, trip_id="T1", *, start=None, end=None, **fields):
    """One typed stop_times row, with times already in seconds.

    `start` and `end` are the pickup/drop-off window, named short because most tests in both
    modules set at least one of them and several turn on setting exactly one; everything else
    is passed under its own column name.
    """
    row = {"_row_number": number, "trip_id": trip_id, "stop_sequence": 1, **fields}
    if start is not None:
        row[START_WINDOW] = start
    if end is not None:
        row[END_WINDOW] = end
    return row
