"""Matching archive entries to tables: case folding, repeats, and the mac wrapper.

Split from test_container.py, which was already near the file-size limit.

Upstream matches an entry to a table descriptor with
`remainingDescriptors.remove(filename.toLowerCase())` (GtfsFeedLoader), and it
collects entry names into an `ImmutableSet` before that (GtfsZipFileInput), so
the match is case-insensitive, a repeated entry name is one file, and the first
entry that folds to a table name is the one that gets loaded. Every assertion
below was measured against the pinned jar on a probe zip built from
tests/fixtures/minimal.zip.
"""

import json
import warnings
import zipfile

from gtfs_validator.cli import main
from gtfs_validator.container import open_feed
from gtfs_validator.notices import NoticeContainer


def make_zip(tmp_path, entries):
    """`entries` is a sequence of pairs, so a name can repeat."""
    path = tmp_path / "feed.zip"
    with warnings.catch_warnings(), zipfile.ZipFile(path, "w") as zf:
        # zipfile warns on a repeated entry name; writing one is the point here.
        warnings.simplefilter("ignore", UserWarning)
        for name, body in entries:
            zf.writestr(name, body)
    return path


def walk(tmp_path, entries):
    return walk_zip(make_zip(tmp_path, entries))


def walk_zip(path):
    feed = open_feed(path)
    notices = NoticeContainer()
    feed.walk(notices)
    return feed, [n for group in notices.grouped().values() for n in group]


def contexts(found, code):
    return [n.context["filename"] for n in found if n.code == code]


def test_a_capitalised_table_is_matched_case_insensitively(tmp_path):
    """Measured on probe `cap_agency`, minimal.zip with agency.txt written as
    Agency.txt: the jar reports neither missing_required_file nor unknown_file for
    it and loads it normally (summary counts Agencies 1). We reported both."""
    feed, found = walk(tmp_path, [("Agency.txt", "agency_name\nAcme\n")])
    assert "agency.txt" not in contexts(found, "missing_required_file")
    assert contexts(found, "unknown_file") == []
    assert feed.filenames == ["agency.txt"]


def test_a_matched_entry_is_read_under_the_archive_spelling(tmp_path):
    """The canonical name is what the loader asks for; the archive entry is what
    has to be opened."""
    feed = open_feed(make_zip(tmp_path, [("Agency.txt", "agency_name\nAcme\n")]))
    with feed.open_table("agency.txt") as handle:
        assert handle.read() == b"agency_name\nAcme\n"
    assert feed.size_of("agency.txt") == len(b"agency_name\nAcme\n")


def test_a_capitalised_table_reports_notices_under_its_canonical_name(tmp_path):
    """Upstream's per-table notices carry `descriptor.gtfsFilename()`, not the
    archive's spelling. Measured on probe `cap_empty`, a zero-byte Agency.txt: the
    jar's empty_file names agency.txt. We named Agency.txt."""
    _, found = walk(tmp_path, [("Agency.txt", "")])
    assert contexts(found, "empty_file") == ["agency.txt"]


def test_a_capitalised_conditional_table_counts_as_present(tmp_path):
    """stops.txt comes from MissingStopsFileValidator rather than the loader, and
    it reads the loaded table, so folding has to reach it too. Measured on probe
    `cap_stops`, minimal.zip with stops.txt written as Stops.TXT: the jar reports
    nothing about stops.txt. We reported missing_required_file plus a
    foreign_key_violation from stop_times.txt against the table we had skipped."""
    _, found = walk(tmp_path, [("Agency.txt", "x\n"), ("Stops.TXT", "stop_id\nS1\n")])
    assert "stops.txt" not in contexts(found, "missing_required_file")
    assert contexts(found, "unknown_file") == []


def test_a_capitalised_locations_geojson_counts_as_present(tmp_path):
    """The geojson has a descriptor in the same map, so it folds like a table.
    Measured: probes `geo_cap` (Locations.GeoJSON) and `geo_lower` draw identical
    reports from the jar, neither reporting stops.txt as missing."""
    _, found = walk(tmp_path, [("agency.txt", "x\n"), ("Locations.GeoJSON", "{}")])
    assert contexts(found, "unknown_file") == []
    assert "stops.txt" not in contexts(found, "missing_required_file")


def test_the_first_spelling_claims_the_table_and_the_second_is_unknown(tmp_path):
    """`remove` empties the slot, so a second entry folding to the same name finds
    no descriptor. Measured on probes `both_lower_first` and `both_cap_first`: the
    jar's unknown_file names whichever of the two comes second in the archive."""
    _, found = walk(tmp_path, [("agency.txt", "x\n"), ("Agency.txt", "y\n")])
    assert contexts(found, "unknown_file") == ["Agency.txt"]

    _, reversed_found = walk(tmp_path, [("Agency.txt", "y\n"), ("agency.txt", "x\n")])
    assert contexts(reversed_found, "unknown_file") == ["agency.txt"]


def test_the_claiming_entry_is_the_one_that_is_read(tmp_path):
    feed = open_feed(make_zip(tmp_path, [("Agency.txt", "first\n"), ("agency.txt", "second\n")]))
    with feed.open_table("agency.txt") as handle:
        assert handle.read() == b"first\n"


def test_a_repeated_entry_name_is_one_file(tmp_path):
    """`getFilenames()` is an ImmutableSet, so the second copy is not a second
    file. Measured on probe `dup_exact`, minimal.zip plus a second zero-byte
    agency.txt: the jar draws no empty_file at all. We drew two."""
    feed, found = walk(tmp_path, [("agency.txt", "agency_name\nAcme\n"), ("agency.txt", "")])
    assert feed.filenames == ["agency.txt"]
    assert contexts(found, "empty_file") == []
    assert contexts(found, "unknown_file") == []


def test_a_repeated_entry_name_is_read_from_the_first_copy(tmp_path):
    """Commons Compress hands the loader the first of two entries; Python's
    ZipFile indexes by name and would hand back the last. Measured on probe
    `dup_exact_rev`, where the zero-byte copy is written first: the jar draws
    empty_file once and counts no agencies, so it read the first copy."""
    feed, found = walk(tmp_path, [("agency.txt", ""), ("agency.txt", "agency_name\nAcme\n")])
    assert contexts(found, "empty_file") == ["agency.txt"]
    with feed.open_table("agency.txt") as handle:
        assert handle.read() == b""


def test_empty_file_is_not_reported_for_an_entry_with_no_table(tmp_path):
    """empty_file comes from CsvFileLoader, which only ever runs on a file that
    matched a descriptor. Measured on probe `unknown_empty`, minimal.zip plus a
    zero-byte notes.txt: the jar reports unknown_file for it and nothing else. We
    reported empty_file too, because the walk tested every root .txt entry."""
    _, found = walk(tmp_path, [("agency.txt", "x\n"), ("notes.txt", "")])
    assert contexts(found, "unknown_file") == ["notes.txt"]
    assert contexts(found, "empty_file") == []


def test_ds_store_is_dropped_from_a_zip_listing(tmp_path):
    """`GtfsZipFileInput` skips it by name, with a comment saying it does so to
    prevent the notice. Measured on probe `ds_store`: the jar reports one
    unknown_file for notes.md and nothing for .DS_Store. We reported both."""
    _, found = walk(tmp_path, [("agency.txt", "x\n"), (".DS_Store", "junk"), ("notes.md", "hi")])
    assert contexts(found, "unknown_file") == ["notes.md"]


def test_ds_store_is_kept_for_a_directory_feed(tmp_path):
    """The skip is `GtfsZipFileInput`'s alone: `GtfsUnarchivedInput` lists every
    regular file. Measured on a directory feed carrying one: the jar reports
    unknown_file for .DS_Store, so dropping it everywhere would be a divergence
    introduced while fixing one."""
    feed_dir = tmp_path / "feed"
    feed_dir.mkdir()
    (feed_dir / "agency.txt").write_text("x\n")
    (feed_dir / ".DS_Store").write_bytes(b"junk")
    feed = open_feed(feed_dir)
    notices = NoticeContainer()
    feed.walk(notices)
    found = [n for group in notices.grouped().values() for n in group]
    assert ".DS_Store" in contexts(found, "unknown_file")


def mac_zip(tmp_path, folder, entries):
    """A zip as Finder writes one: a directory entry, then everything under it."""
    path = tmp_path / "feed.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{folder}/", b"")
        for name, body in entries:
            zf.writestr(f"{folder}/{name}", body)
    return path


def test_a_wrapper_folder_named_after_the_archive_is_stripped(tmp_path):
    """Upstream unwraps `feed.zip` holding `feed/agency.txt` back to agency.txt.
    Measured on probe `macfeed`: the jar's summary lists the unwrapped names and
    it reports no missing_required_file."""
    feed = open_feed(mac_zip(tmp_path, "feed", [("agency.txt", "x\n"), ("notes.md", "hi")]))
    assert feed.root_files == ["agency.txt", "notes.md"]
    assert feed.filenames == ["agency.txt"]


def test_an_unwrapped_table_is_listed_but_not_readable(tmp_path):
    """The unwrap rewrites the listing and not the reads, which is upstream's bug
    and the whole reason a mac-wrapped feed fails on the jar. Measured on
    `macfeed`: six tables, six csv_parsing_failed, no empty_file and no
    missing_required_file."""
    feed, found = walk_zip(mac_zip(tmp_path, "feed", [("agency.txt", ""), ("stops.txt", "x\n")]))
    assert not feed.is_readable("agency.txt")
    assert contexts(found, "empty_file") == []
    # Descriptor-map order, not alphabetical; see test_container.py.
    assert contexts(found, "missing_required_file") == ["stop_times.txt", "routes.txt", "trips.txt"]
    # Unwrapping does not touch the subfolder test, which upstream runs over the
    # raw entry names in a separate pass of the archive.
    assert [n.code for n in found if n.code == "invalid_input_files_in_subfolder"] == [
        "invalid_input_files_in_subfolder"
    ]


def test_an_unwrapped_table_is_reported_as_a_parse_failure(tmp_path):
    """End to end, because the notice comes from the loader rather than the walk.

    Measured on probe `macfeed`, minimal.zip wrapped in a folder named after the
    archive: the jar reports csv_parsing_failed for each of the six tables, with
    this exact context, and writes an empty system_errors.json. Reading a name the
    archive does not hold is a crash on the way to that notice, not a system error.
    """
    feed = mac_zip(tmp_path, "feed", [("agency.txt", "agency_name\nAcme\n")])
    out = tmp_path / "out"
    main(["-i", str(feed), "-o", str(out), "-d", "2026-06-01"])
    report = json.loads((out / "report.json").read_text())
    failures = [n for n in report["notices"] if n["code"] == "csv_parsing_failed"]
    assert failures[0]["sampleNotices"] == [
        {
            "filename": "agency.txt",
            "charIndex": 0,
            "columnIndex": -1,
            "lineIndex": -1,
            "message": "origin",
            "parsedContent": "",
        }
    ]
    assert json.loads((out / "system_errors.json").read_text())["notices"] == []


def test_a_wrapper_folder_with_another_name_is_left_alone(tmp_path):
    """The flag is set only by a directory entry named after the archive. Measured
    on probe `macfeed_other`, whose wrapper is `inner/`: the jar reports five
    missing_required_file and an empty file listing."""
    feed = open_feed(mac_zip(tmp_path, "inner", [("agency.txt", "x\n")]))
    assert feed.root_files == []
    assert feed.filenames == []


def test_a_subfolder_table_outside_the_gtfs_files_enum_is_ignored(tmp_path):
    """`containsGtfsFileInSubfolder` reads `GtfsFiles`, a hand-maintained enum of 23
    names, not the 31 generated descriptors. Measured on probe `sub_booking`,
    minimal.zip plus extra/booking_rules.txt: the jar reports nothing, and we
    reported invalid_input_files_in_subfolder at ERROR."""
    for name in ("extra/booking_rules.txt", "extra/timeframes.txt", "extra/networks.txt"):
        _, found = walk(tmp_path, [("agency.txt", "x\n"), (name, "x\n")])
        assert [n.code for n in found if n.code == "invalid_input_files_in_subfolder"] == [], name


def test_a_subfolder_table_is_still_matched_case_sensitively(tmp_path):
    """The contrast is deliberate: `GtfsFiles.containsGtfsFile` compares with
    `equals`, while the root match folds. Measured on probe `sub_cap`, minimal.zip
    plus extra/Agency.txt: the jar reports no invalid_input_files_in_subfolder."""
    _, found = walk(tmp_path, [("agency.txt", "x\n"), ("extra/Agency.txt", "x\n")])
    assert [n.code for n in found if n.code == "invalid_input_files_in_subfolder"] == []
