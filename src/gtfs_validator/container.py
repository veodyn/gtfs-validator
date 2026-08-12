"""Stage 1: locate the tables in a feed and report container-level problems.

Entries are streamed out of the archive rather than extracted, so zip path
traversal is not reachable.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import IO

from gtfs_validator import javahash, schema
from gtfs_validator.notices import Notice, NoticeContainer, Severity

# Upstream's engine emits missing_required_file only for tables annotated
# @Required, which is these four. stops.txt and feed_info.txt are
# @ConditionallyRequired at table level, and two rule-layer validators decide
# them instead: see _check_conditional_files.
REQUIRED_FILES = schema.REQUIRED_FILES
RECOMMENDED_FILES = schema.RECOMMENDED_FILES
# locations.geojson is a GTFS input upstream recognises
# (GtfsGeoJsonFeature.FILENAME) but not a .txt table, so the generated table
# registry does not carry it. Without it the file draws unknown_file, and it is
# matched against the archive root rather than against the parsed table list.
GEOJSON_FILE = "locations.geojson"
KNOWN_FILES = schema.KNOWN_FILES | {GEOJSON_FILE}

# Upstream keeps its table descriptors in `HashMap<String, GtfsFileDescriptor<?>>` keyed by filename
# and reports every table it could not find by iterating a clone of it, so the order of those notices
# is Java's bucket order. The capacity is 64: 32 descriptors clone into a map sized
# `tableSizeFor(32 / 0.75 + 1)`.
#
# Measured on real feeds `1104-RO` and `1807-ML`, whose missing four come out
# stop_times, agency, routes, trips. Alphabetical order gives agency first.
#
# **Within-bucket order is not modelled.** Three buckets hold more than one table name, and Java
# would order those by insertion, which is the order upstream registers descriptors and is not
# recorded anywhere we can read. It does not matter for the notices that use this: every colliding
# name is an optional table, so none of them can be a missing *required* or *recommended* file. A
# future notice reporting optional tables in this order would need the insertion order measured.
_DESCRIPTOR_ORDER = {
    name: position
    for position, name in enumerate(
        sorted(KNOWN_FILES, key=lambda name: 63 & javahash.spread(javahash.string_hash(name)))
    )
}


def descriptor_order(names: Iterable[str]) -> list[str]:
    """`names` in the order upstream's descriptor map yields them."""
    return sorted(names, key=lambda name: _DESCRIPTOR_ORDER.get(name, len(_DESCRIPTOR_ORDER)))


class FeedContainer:
    def __init__(self, path: Path, names: list[str], zf: zipfile.ZipFile | None) -> None:
        self.path = path
        self._zf = zf
        self._all_names = names
        # root_files is everything at the archive root; entry_of maps each GTFS
        # file the archive carries to the entry it is carried under, and filenames
        # is the table subset of that, which is what gets parsed.
        #
        # The archive's own order, not sorted. Upstream walks `gtfsInput.getFilenames()` and submits
        # one loader per file to an executor it runs single-threaded, so a zip's entry order is the
        # order every per-row notice is emitted in, and therefore which samples survive the
        # 1,000-sample cap. Measured on probe `tblorder`: the jar's notices come out in the order the
        # entries were written, which sorting reverses for most feeds. Found by the real-feed corpus,
        # as `mixed_case_recommended_field` samples in a different order from the jar's on four of
        # six feeds that otherwise agreed on every notice.
        #
        # Deduplicated because `GtfsZipFileInput` collects entry names into an
        # ImmutableSet, so a name the archive repeats is one file to everything
        # downstream. Measured on probe `dup_exact`, a zip carrying agency.txt
        # twice: the jar loads it once.
        self.root_files = list(dict.fromkeys(n for n in names if "/" not in n and n))
        # GtfsFeedLoader matches an entry to a table with
        # `remainingDescriptors.remove(filename.toLowerCase())`, so the match folds
        # case and the first entry that folds to a table name takes the descriptor
        # with it: a later entry folding to the same name finds nothing and draws
        # unknown_file. Measured on probes `cap_agency` (Agency.txt validates as
        # agency.txt) and `both_cap_first` (the jar's unknown_file names whichever
        # spelling comes second). Java's toLowerCase is locale-dependent and this
        # is not; the two agree on every ASCII table name.
        self.entry_of: dict[str, str] = {}
        self.unknown_files: list[str] = []
        for name in self.root_files:
            canonical = name.lower()
            if canonical in KNOWN_FILES and canonical not in self.entry_of:
                self.entry_of[canonical] = name
            else:
                self.unknown_files.append(name)
        # Keyed by the canonical name, because that is what upstream's notices,
        # schemas and table containers are keyed by: the descriptor carries
        # `gtfsFilename()` into every per-table notice, not the archive's spelling.
        # Measured on probe `cap_empty`: a zero-byte Agency.txt draws empty_file
        # for agency.txt.
        self.filenames = [name for name in self.entry_of if name.endswith(".txt")]
        # Python's ZipFile indexes by name and keeps the last entry of a repeated
        # name, where Commons Compress hands the loader the first. Measured on
        # probe `dup_exact_rev`, whose first agency.txt is the empty one: the jar
        # draws empty_file and counts no agencies, so it read the first.
        self._entries: dict[str, zipfile.ZipInfo] = {}
        if zf is not None:
            for info in zf.infolist():
                self._entries.setdefault(info.filename, info)

    def has_subfolder_tables(self) -> bool:
        """containsGtfsFileInSubfolder: a nested entry named after a GtfsFiles constant.

        Three things about the comparison, each of them measured rather than
        assumed, and each the opposite of what the root-level match does:

          * The set is `GtfsFiles`, upstream's hand-maintained enum of 23 names,
            not the 31 generated descriptors. A nested booking_rules.txt draws
            nothing from the jar; matching against the descriptors drew an ERROR.
          * `GtfsFiles.containsGtfsFile` compares with `equals`, so extra/Agency.txt
            draws nothing either, where the root match folds case.
          * The basename is tested against that set rather than against ".txt", so
            neither extra/notes.txt nor extra/locations.geojson counts: the geojson
            is a GTFS input at the root but is not in the enum.

        Raw entry names, before the mac-wrapper unwrap: upstream runs this over
        its own pass of the zip stream, ahead of building the filename set.
        """
        return any(
            "/" in name and name.rsplit("/", 1)[-1] in schema.GTFS_FILES_ENUM
            for name in self._all_names
        )

    def entry_name(self, name: str) -> str:
        """The archive's spelling of a canonical GTFS filename.

        A name the archive does not carry passes through, so a caller asking for a
        missing table still gets the archive's own KeyError rather than this one's.
        """
        return self.entry_of.get(name, name)

    def open_table(self, name: str) -> IO[bytes]:
        entry = self.entry_name(name)
        if self._zf is not None:
            return self._zf.open(self._entries.get(entry, entry))
        return (self.path / entry).open("rb")

    def size_of(self, name: str) -> int:
        entry = self.entry_name(name)
        if self._zf is not None:
            return self._entries[entry].file_size
        return (self.path / entry).stat().st_size

    def walk(self, notices: NoticeContainer) -> None:
        # GtfsInput adds this notice and then returns the input, so the loader
        # goes on to report every table it cannot find. Short-circuiting here
        # suppressed six notices the jar emits for a feed nested one level down,
        # and the condition has no clause about the root: a zip carrying tables at
        # both levels draws it too.
        if self.has_subfolder_tables():
            notices.add(Notice("invalid_input_files_in_subfolder", Severity.ERROR, {}))

        present = set(self.filenames)
        for name in descriptor_order(REQUIRED_FILES - present):
            notices.add(Notice("missing_required_file", Severity.ERROR, {"filename": name}))
        for name in descriptor_order(RECOMMENDED_FILES - present):
            notices.add(Notice("missing_recommended_file", Severity.WARNING, {"filename": name}))
        # Unknown covers every root entry that did not claim a GTFS file, including
        # non-.txt files like a stray README, and reports the archive's spelling
        # rather than a canonical name. Archive order, because upstream emits this
        # inside its walk over getFilenames(); see root_files.
        for name in self.unknown_files:
            notices.add(Notice("unknown_file", Severity.INFO, {"filename": name}))
        self._check_conditional_files(present, notices)
        # Only files that matched a descriptor: upstream emits empty_file from
        # CsvFileLoader, which never runs on an entry it has no table for.
        # Measured on probe `unknown_empty`, a zero-byte notes.txt: the jar reports
        # unknown_file for it and nothing else.
        for name in self.filenames:
            if self.size_of(name) == 0:
                notices.add(Notice("empty_file", Severity.ERROR, {"filename": name}))

    def _check_conditional_files(self, present: set[str], notices: NoticeContainer) -> None:
        """The two upstream FileValidators whose condition is the file listing.

        MissingStopsFileValidator wants stops.txt only when locations.geojson is
        also absent, and MissingFeedInfoValidator escalates feed_info.txt from
        recommended to required when translations.txt is present. Approximating
        both with static sets reported a spurious missing_required_file on a
        geojson-only feed and the wrong severity on a translated one.
        """
        if "stops.txt" not in present and GEOJSON_FILE not in self.entry_of:
            notices.add(Notice("missing_required_file", Severity.ERROR, {"filename": "stops.txt"}))
        if "feed_info.txt" not in present:
            if "translations.txt" in present:
                notices.add(
                    Notice("missing_required_file", Severity.ERROR, {"filename": "feed_info.txt"})
                )
            else:
                notices.add(
                    Notice(
                        "missing_recommended_file",
                        Severity.WARNING,
                        {"filename": "feed_info.txt"},
                    )
                )

    def close(self) -> None:
        if self._zf is not None:
            self._zf.close()


def open_feed(path: Path) -> FeedContainer:
    path = Path(path)
    if path.is_dir():
        names = [p.name for p in path.iterdir() if p.is_file()]
        return FeedContainer(path, names, None)
    zf = zipfile.ZipFile(path)
    return FeedContainer(path, zf.namelist(), zf)
