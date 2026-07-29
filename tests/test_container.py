import zipfile
from pathlib import Path

from gtfs_validator.container import FeedContainer, open_feed
from gtfs_validator.notices import NoticeContainer


def make_zip(tmp_path, entries):
    path = tmp_path / "feed.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    return path


def all_notices(container):
    return [n for group in container.grouped().values() for n in group]


def test_missing_required_file_fires_for_each_absent_table(tmp_path):
    feed = open_feed(make_zip(tmp_path, {"agency.txt": "agency_name\nAcme\n"}))
    notices = NoticeContainer()
    feed.walk(notices)
    missing = {
        n.context["filename"] for n in all_notices(notices) if n.code == "missing_required_file"
    }
    assert missing == {"stops.txt", "routes.txt", "trips.txt", "stop_times.txt"}


def test_unknown_file_covers_non_table_entries(tmp_path):
    # notes.md is not a .txt table, so it must still be reported as unknown.
    feed = open_feed(make_zip(tmp_path, {"agency.txt": "x\n", "notes.md": "hi"}))
    notices = NoticeContainer()
    feed.walk(notices)
    unknown = [n for n in all_notices(notices) if n.code == "unknown_file"]
    assert [n.context for n in unknown] == [{"filename": "notes.md"}]


def test_empty_file_fires_on_zero_bytes(tmp_path):
    feed = open_feed(make_zip(tmp_path, {"agency.txt": ""}))
    notices = NoticeContainer()
    feed.walk(notices)
    empty = [n for n in all_notices(notices) if n.code == "empty_file"]
    assert empty[0].context == {"filename": "agency.txt"}


def test_files_in_subfolder_emit_one_context_free_notice(tmp_path):
    feed = open_feed(make_zip(tmp_path, {"feed/agency.txt": "x\n", "feed/stops.txt": "y\n"}))
    notices = NoticeContainer()
    feed.walk(notices)
    sub = [n for n in all_notices(notices) if n.code == "invalid_input_files_in_subfolder"]
    assert len(sub) == 1
    assert sub[0].context == {}
    # The walk does *not* short-circuit. This assertion originally read
    # `== ["invalid_input_files_in_subfolder"]`, which encoded an assumption as a
    # test and made the wrong behaviour look verified for four plans. Measured:
    # the jar reports the missing-file notices on top of this one, because
    # GtfsInput adds the notice and returns the input rather than bailing.
    assert "missing_required_file" in {n.code for n in all_notices(notices)}


def test_directory_input_is_supported(tmp_path):
    feed_dir = tmp_path / "feed"
    feed_dir.mkdir()
    (feed_dir / "agency.txt").write_text("agency_name\nAcme\n")
    feed = open_feed(feed_dir)
    assert "agency.txt" in feed.filenames


def test_fares_v2_tables_are_not_reported_unknown(tmp_path):
    # Regression: plan 1's hand-written KNOWN_FILES omitted the Fares v2 tables,
    # so a conformant feed using them drew one spurious unknown_file each.
    feed = open_feed(
        make_zip(
            tmp_path,
            {
                "agency.txt": "x\n",
                "fare_media.txt": "fare_media_id\n1\n",
                "areas.txt": "area_id\nA1\n",
                "networks.txt": "network_id\nN1\n",
            },
        )
    )
    notices = NoticeContainer()
    feed.walk(notices)
    unknown = [n.context["filename"] for n in all_notices(notices) if n.code == "unknown_file"]
    assert unknown == []


def test_open_table_streams_bytes(tmp_path):
    feed = open_feed(make_zip(tmp_path, {"agency.txt": "agency_name\nAcme\n"}))
    with feed.open_table("agency.txt") as handle:
        assert handle.read() == b"agency_name\nAcme\n"


def _reported(notices, code):
    return {n.context["filename"] for n in all_notices(notices) if n.code == code}


def test_stops_is_not_required_when_locations_geojson_is_present(tmp_path):
    # MissingStopsFileValidator wants both absent before it reports. Measured:
    # the jar says nothing about stops.txt for a feed carrying locations.geojson.
    feed = open_feed(make_zip(tmp_path, {"agency.txt": "x\n", "locations.geojson": '{"type":"X"}'}))
    notices = NoticeContainer()
    feed.walk(notices)
    assert "stops.txt" not in _reported(notices, "missing_required_file")


def test_stops_is_required_when_neither_is_present(tmp_path):
    feed = open_feed(make_zip(tmp_path, {"agency.txt": "x\n"}))
    notices = NoticeContainer()
    feed.walk(notices)
    assert "stops.txt" in _reported(notices, "missing_required_file")


def test_feed_info_is_required_when_translations_is_present(tmp_path):
    # MissingFeedInfoValidator escalates rather than skipping. Measured: the jar
    # reports missing_required_file, not missing_recommended_file.
    feed = open_feed(make_zip(tmp_path, {"agency.txt": "x\n", "translations.txt": "y\n"}))
    notices = NoticeContainer()
    feed.walk(notices)
    assert "feed_info.txt" in _reported(notices, "missing_required_file")
    assert "feed_info.txt" not in _reported(notices, "missing_recommended_file")


def test_feed_info_is_only_recommended_without_translations(tmp_path):
    feed = open_feed(make_zip(tmp_path, {"agency.txt": "x\n"}))
    notices = NoticeContainer()
    feed.walk(notices)
    assert "feed_info.txt" in _reported(notices, "missing_recommended_file")
    assert "feed_info.txt" not in _reported(notices, "missing_required_file")


def test_a_present_feed_info_draws_neither_notice(tmp_path):
    feed = open_feed(make_zip(tmp_path, {"agency.txt": "x\n", "feed_info.txt": "y\n"}))
    notices = NoticeContainer()
    feed.walk(notices)
    assert "feed_info.txt" not in _reported(notices, "missing_recommended_file")
    assert "feed_info.txt" not in _reported(notices, "missing_required_file")


def test_locations_geojson_is_a_known_file(tmp_path):
    # It is a GTFS input upstream reads (GtfsGeoJsonFeature.FILENAME) rather than
    # a stray entry, but it is not a .txt table, so the generated registry does
    # not list it. Measured: the jar reports no unknown_file for it.
    feed = open_feed(make_zip(tmp_path, {"agency.txt": "x\n", "locations.geojson": "{}"}))
    notices = NoticeContainer()
    feed.walk(notices)
    assert "locations.geojson" not in _reported(notices, "unknown_file")


NESTED_TABLES = {
    "feed/agency.txt": "agency_id,agency_name\n1,Acme\n",
    "feed/stops.txt": "stop_id\nS1\n",
}


def test_a_nested_feed_still_reports_its_missing_files(tmp_path):
    # Upstream's GtfsInput adds the notice and then returns the input, so the
    # loader goes on to find every table missing. Measured on a zip holding only
    # feed/*.txt: the jar reports invalid_input_files_in_subfolder plus five
    # missing_required_file, one missing_recommended_file and
    # missing_calendar_and_calendar_date_files. Short-circuiting the walk
    # suppressed six of those.
    feed = open_feed(make_zip(tmp_path, NESTED_TABLES))
    notices = NoticeContainer()
    feed.walk(notices)
    codes = {n.code for n in all_notices(notices)}
    assert "invalid_input_files_in_subfolder" in codes
    assert "missing_required_file" in codes
    assert _reported(notices, "missing_required_file") >= {"agency.txt", "routes.txt"}


def test_a_subfolder_table_is_reported_even_when_the_root_has_tables(tmp_path):
    # The condition is hasSubfolderWithGtfsFile alone, with no clause about the
    # root. Measured: a zip with a full set of root tables plus extra/agency.txt
    # draws the notice from the jar, and drew nothing from us.
    entries = {"agency.txt": "agency_id\n1\n", "extra/agency.txt": "agency_id\n1\n"}
    feed = open_feed(make_zip(tmp_path, entries))
    notices = NoticeContainer()
    feed.walk(notices)
    assert "invalid_input_files_in_subfolder" in {n.code for n in all_notices(notices)}


def test_a_subfolder_file_that_is_not_a_gtfs_table_is_ignored(tmp_path):
    # containsGtfsFileInSubfolder tests the basename against the known table set,
    # not against ".txt". Measured: neither extra/notes.txt nor
    # extra/locations.geojson draws the notice from the jar, so the geojson is not
    # in that set even though it is a GTFS input at the root.
    for name in ("extra/notes.txt", "extra/locations.geojson"):
        entries = {"agency.txt": "agency_id\n1\n", name: "x"}
        feed = open_feed(make_zip(tmp_path, entries))
        notices = NoticeContainer()
        feed.walk(notices)
        assert "invalid_input_files_in_subfolder" not in {n.code for n in all_notices(notices)}, (
            name
        )


def test_root_files_keep_the_archive_order_rather_than_sorting():
    """Upstream visits `gtfsInput.getFilenames()` in the archive's own order, not sorted.

    Measured on probe `tblorder`, a zip whose entries are written agency, stops, routes, trips,
    stop_times, calendar, calendar_dates, feed_info, frequencies, transfers, attributions, levels,
    pathways. The jar's `non_ascii_or_non_printable_char` samples come out
    calendar_dates, transfers, attributions, levels, pathways, which is that order filtered to the
    five tables whose id fields carry the character. Sorted order would be attributions,
    calendar_dates, levels, pathways, transfers.

    This decides the order of every per-row notice, and therefore which samples survive the
    1,000-sample cap. It showed up first as `mixed_case_recommended_field` samples in a different
    order from the jar's on 4 of 6 real feeds that otherwise matched completely.
    """
    names = ["stops.txt", "agency.txt", "routes.txt"]
    feed = FeedContainer(Path("feed.zip"), names, None)
    assert feed.root_files == names
    assert feed.filenames == names


def test_missing_required_files_come_out_in_upstream_hashmap_order(tmp_path):
    """Measured on real feeds `1104-RO` and `1807-ML`: the jar orders them stop_times, agency,
    routes, trips, and then stops.txt last.

    Upstream iterates `remainingDescriptors.values()`, a clone of a
    `HashMap<String, GtfsFileDescriptor>` keyed by filename, so the order is Java's bucket order at
    the capacity 32 descriptors give it, which is 64. Alphabetical order puts agency first and is
    what this code did until the real-feed corpus showed the difference.

    stops.txt is not in that loop at all: upstream reports it from `MissingStopsFileValidator`, which
    runs after the loader, which is why it trails the four.
    """
    feed = open_feed(make_zip(tmp_path, {"calendar.txt": "service_id\nS1\n"}))
    notices = NoticeContainer()
    feed.walk(notices)
    missing = [n.context["filename"] for n in all_notices(notices)
               if n.code == "missing_required_file"]
    assert missing == ["stop_times.txt", "agency.txt", "routes.txt", "trips.txt", "stops.txt"]


def test_unknown_files_come_out_in_archive_order(tmp_path):
    """`unknown_file` is emitted inside upstream's walk over `getFilenames()`, so it follows the
    archive rather than the alphabet, for the same reason the per-row notices do."""
    feed = open_feed(make_zip(tmp_path, {"zebra.txt": "a\n", "apple.txt": "b\n"}))
    notices = NoticeContainer()
    feed.walk(notices)
    unknown = [n.context["filename"] for n in all_notices(notices) if n.code == "unknown_file"]
    assert unknown == ["zebra.txt", "apple.txt"]
