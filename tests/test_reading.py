"""The public read-only loader: load a feed, read its rows, run no rules.

`run_validation` has always composed these stages and then closed the store on
its way out, so nothing outside this package could load a feed and look at it.
The GTFS-Realtime validator needs exactly that and nothing else: it validates
realtime messages *against* a static feed, so it wants the tables and none of
the notices.
"""

import sqlite3
import zipfile

import pytest

from gtfs_validator.reading import open_feed_view
from gtfs_validator.rules.feedview import DependencyFailed


def make_feed(tmp_path):
    """A conformant feed, the same shape tests/test_cli.py builds."""
    path = tmp_path / "feed.zip"
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
        zf.writestr("trips.txt", "route_id,service_id,trip_id\nR1,WEEK,T1\n")
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
