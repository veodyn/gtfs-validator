"""The public read-only loader: load a feed, read its rows, run no rules.

`run_validation` has always composed these stages and then closed the store on
its way out, so nothing outside this package could load a feed and look at it.
The GTFS-Realtime validator needs exactly that and nothing else: it validates
realtime messages *against* a static feed, so it wants the tables and none of
the notices.

The second half of this module covers `open_raw_view`, the untyped read surface
beside it. Its whole point is answering for a table the strict path refuses, so
every test there is written against a feed this one's loader marks unusable.
"""

import sqlite3
import zipfile

import pytest

from gtfs_validator.reading import open_feed_view, open_raw_view
from gtfs_validator.rules.feedview import DependencyFailed

GOOD_TRIPS = "route_id,service_id,trip_id\nR1,WEEK,T1\n"


def make_feed(tmp_path, trips=GOOD_TRIPS, name="feed.zip"):
    """A conformant feed, the same shape tests/test_cli.py builds.

    `trips` is a parameter so a caller can swap in a trips.txt the strict path
    refuses. Writing a second entry into the finished archive would not do it:
    `GtfsZipFileInput` collects entry names into a set and Commons Compress
    hands the loader the first of a repeated name, which `container` reproduces.
    """
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "agency.txt",
            "agency_id,agency_name,agency_url,agency_timezone\n"
            "1,Acme Transit,https://example.com,America/New_York\n",
        )
        zf.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\nS1,Main St,40.7,-74.0\n")
        zf.writestr(
            "routes.txt",
            "route_id,agency_id,route_short_name,route_type\nR1,1,10,3\n",
        )
        zf.writestr("trips.txt", trips)
        zf.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n",
        )
        zf.writestr(
            "calendar.txt",
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,"
            "sunday,start_date,end_date\nWEEK,1,1,1,1,1,0,0,20260101,20261231\n",
        )
    return path


def test_rows_are_readable_inside_the_context(tmp_path):
    with open_feed_view(make_feed(tmp_path)) as loaded:
        trips = list(loaded.view.rows("trips.txt"))
    assert [row["trip_id"] for row in trips] == ["T1"]


def test_typed_columns_arrive_typed(tmp_path):
    """The value of using this loader rather than csv.reader: stage 3 has run."""
    with open_feed_view(make_feed(tmp_path)) as loaded:
        stop = next(iter(loaded.view.rows("stops.txt")))
    assert stop["stop_lat"] == 40.7


def test_tables_argument_loads_only_what_was_asked_for(tmp_path):
    """The realtime validator wants 7 tables, not 32, and replays against them."""
    with open_feed_view(make_feed(tmp_path), tables=["trips.txt"]) as loaded:
        assert [row["trip_id"] for row in loaded.view.rows("trips.txt")] == ["T1"]
        assert loaded.tables == frozenset({"trips.txt"})


def test_an_unrequested_table_raises_rather_than_reading_empty(tmp_path):
    """A table left out of `tables` must not look like a table with no rows.

    `FeedStore.rows` answers an unregistered table with an empty iterator, so
    without the status check a caller that forgot to request stop_times.txt would
    conclude the feed has no stop times rather than that it never loaded them.
    For a realtime rule that is the difference between "no findings" and "every
    trip is unknown".
    """
    with (
        open_feed_view(make_feed(tmp_path), tables=["trips.txt"]) as loaded,
        pytest.raises(DependencyFailed),
    ):
        list(loaded.view.rows("stop_times.txt"))


def test_the_feeds_own_notices_are_available_rather_than_discarded(tmp_path):
    """Loading computes them anyway, and a caller validating against this feed
    wants to know the feed is broken before blaming the realtime data."""
    path = tmp_path / "broken.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("agency.txt", "agency_id,agency_name,agency_url,agency_timezone\n1,A,,\n")
    with open_feed_view(path) as loaded:
        codes = {notice.code for notice in loaded.notices.in_order()}
    assert "missing_required_field" in codes


def test_the_store_is_closed_on_the_way_out(tmp_path):
    """The context manager owns the temporary database, so a caller cannot leak
    one by holding the view past the block."""
    with open_feed_view(make_feed(tmp_path)) as loaded:
        view = loaded.view
    with pytest.raises(sqlite3.ProgrammingError):
        list(view.rows("trips.txt"))


def test_the_loader_is_reachable_from_the_package_root(tmp_path):
    """`FeedView` is the read surface 68 rule modules already depend on, so it is
    the most change-resistant thing in this package. Exporting it says so out
    loud, because a caller outside this repository now pins on it."""
    import gtfs_validator

    assert "open_feed_view" in gtfs_validator.__all__
    with gtfs_validator.open_feed_view(make_feed(tmp_path)) as loaded:
        assert loaded.tables


# --- open_raw_view: the same archive, read as onebusaway reads it ------------


def make_untypeable_feed(tmp_path):
    """`make_feed` with a `direction_id` of `N`, which is not 0 or 1.

    The shape MobilityData's own `testagency.zip` carries, and the reason this
    read surface exists: strict typing refuses the cell, so the whole of
    trips.txt stops being readable, while a caller that wanted the text was
    never going to type it in the first place.
    """
    return make_feed(
        tmp_path,
        trips="route_id,service_id,trip_id,direction_id\nR1,WEEK,T1,N\n",
        name="untypeable.zip",
    )


def test_the_strict_path_refuses_the_table_this_one_must_still_answer_for(tmp_path):
    """The premise, asserted rather than assumed, so the tests below mean something."""
    with open_feed_view(make_untypeable_feed(tmp_path)) as loaded:
        assert loaded.view.dependency_failed("trips.txt")


def test_rows_come_back_for_a_table_the_strict_path_marks_failed(tmp_path):
    with open_raw_view(make_untypeable_feed(tmp_path)) as raw:
        trips = list(raw.rows("trips.txt"))
    assert [row["direction_id"] for row in trips] == ["N"]


def test_every_cell_is_the_string_the_file_holds(tmp_path):
    """The opposite of `test_typed_columns_arrive_typed`, and the whole contract.

    A caller reproducing onebusaway's untyped reader needs `40.7` and not 40.7:
    the text is what its comparisons are written against.
    """
    with open_raw_view(make_feed(tmp_path)) as raw:
        stop = next(iter(raw.rows("stops.txt")))
    assert stop["stop_lat"] == "40.7"


def test_rows_carry_the_row_number_the_strict_path_assigns(tmp_path):
    """Same numbering, so a caller can line the two reads up: 1-based including
    the header, which puts the first data row at 2."""
    with open_raw_view(make_feed(tmp_path)) as raw:
        assert [row["_row_number"] for row in raw.rows("stops.txt")] == [2]


def test_an_absent_value_is_the_empty_string_rather_than_none(tmp_path):
    """Nothing is mapped, so a blank cell stays blank. Deciding that a blank
    means null is the caller's, because whose null it is depends on the model
    the caller is reproducing."""
    path = tmp_path / "blank.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("trips.txt", "route_id,service_id,trip_id,direction_id\nR1,WEEK,T1,\n")
    with open_raw_view(path) as raw:
        assert next(iter(raw.rows("trips.txt")))["direction_id"] == ""


def test_a_repeated_column_name_does_not_cost_the_table_its_rows(tmp_path):
    """The strict path returns INVALID_HEADERS here and reads no rows at all.

    Header errors are the second way a table can fail wholesale, and a reader
    with no schema has no opinion about them, so the rows still arrive.
    """
    path = tmp_path / "dup.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("trips.txt", "route_id,service_id,trip_id,trip_id\nR1,WEEK,T1,T1\n")
    with open_raw_view(path) as raw:
        assert [row["route_id"] for row in raw.rows("trips.txt")] == ["R1"]


def test_a_table_the_archive_lacks_reads_as_missing_rather_than_raising(tmp_path):
    with open_raw_view(make_feed(tmp_path)) as raw:
        assert raw.is_missing("frequencies.txt")
        assert list(raw.rows("frequencies.txt")) == []
        assert not raw.is_missing("trips.txt")


def test_tables_restricts_what_may_be_read(tmp_path):
    """`tables=` is the same promise the strict path makes: ask for what you
    need, and asking for anything else is a mistake rather than an empty read."""
    with open_raw_view(make_feed(tmp_path), tables=["trips.txt"]) as raw:
        assert raw.tables == frozenset({"trips.txt"})
        with pytest.raises(KeyError):
            list(raw.rows("stops.txt"))


def test_the_raw_reader_is_reachable_from_the_package_root(tmp_path):
    import gtfs_validator

    assert "open_raw_view" in gtfs_validator.__all__
    with gtfs_validator.open_raw_view(make_untypeable_feed(tmp_path)) as raw:
        assert list(raw.rows("trips.txt"))
