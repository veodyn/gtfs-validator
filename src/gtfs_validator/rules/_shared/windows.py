"""The pickup/drop-off window columns, and the two ways an absent one is rendered.

An absent window renders as `"00:00:00"` for the two PickupDropOffType notices, and the key
is **omitted** for the three PickupDropOffWindowValidator ones. Both fields are `GtfsTime`,
so the type does not decide it: what differs is that one constructor is passed the getter,
whose value for an unset field is `GtfsTime`'s zero, and the other is passed an explicit
`null`, which gson drops.

That makes three distinct answers for an absent value, all measured:

- a `String` field shows the generated entity's default, so `""` (attributionId, stopName)
- an explicitly null-passed field is dropped by gson (window_fields below)
- a `GtfsTime` field shows zero formatted, so `"00:00:00"` (window_context below)

Which one applies has to be measured per notice. Reading the field's Java type is not
enough, and these two functions sitting in one module is the evidence: same type, same
column, opposite renderings.
"""

from __future__ import annotations

from gtfs_validator.rules._shared.render import hhmmss

START_WINDOW = "start_pickup_drop_off_window"
END_WINDOW = "end_pickup_drop_off_window"
WINDOW_COLUMNS = (START_WINDOW, END_WINDOW)
# GtfsTime's default, which its adapter renders rather than omitting.
ABSENT_TIME = 0


def has_window(row: dict) -> bool:
    return any(row.get(column) is not None for column in WINDOW_COLUMNS)


def window_context(row: dict) -> dict:
    return {
        "startPickupDropOffWindow": hhmmss(row.get(START_WINDOW) or ABSENT_TIME),
        "endPickupDropOffWindow": hhmmss(row.get(END_WINDOW) or ABSENT_TIME),
    }


def has_both_windows(row: dict) -> bool:
    return all(row.get(column) is not None for column in WINDOW_COLUMNS)


# The notice keys PickupDropOffWindowValidator's three codes carry, paired with their
# columns and in gson's field order, which is Java declaration order.
TIME_FIELDS = (
    ("arrivalTime", "arrival_time"),
    ("departureTime", "departure_time"),
    ("startPickupDropOffWindow", START_WINDOW),
    ("endPickupDropOffWindow", END_WINDOW),
)
WINDOW_FIELDS = TIME_FIELDS[2:]


def present_times(row: dict, fields: tuple[tuple[str, str], ...]) -> dict:
    """Context entries for the times a row carries, with the absent ones omitted entirely.

    The complement of window_context: this is the null-passed convention, where a row with
    one end of a window produces a one-key context rather than one padded with midnight.
    """
    return {key: hhmmss(row[column]) for key, column in fields if row.get(column) is not None}
