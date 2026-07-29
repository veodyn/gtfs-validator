from gtfs_validator.notices import Notice, NoticeContainer, Severity


def test_severity_ordinals_match_upstream():
    # Upstream SeverityLevel declares INFO, WARNING, ERROR in this order and the
    # report grouping key depends on the ordinal. Do not reorder.
    assert (Severity.INFO, Severity.WARNING, Severity.ERROR) == (0, 1, 2)


def test_mapping_key_is_code_plus_ordinal():
    notice = Notice("empty_file", Severity.ERROR, {"filename": "stops.txt"})
    assert notice.mapping_key == "empty_file2"


def test_notice_is_hashable_and_frozen():
    notice = Notice("unknown_file", Severity.INFO, {"filename": "extra.txt"})
    assert notice.context["filename"] == "extra.txt"


def test_counts_are_uncapped_but_retention_is_capped():
    container = NoticeContainer(max_total=10, max_per_type=3, max_exports_per_type=2)
    for i in range(7):
        container.add(Notice("empty_row", Severity.WARNING, {"csvRowNumber": i}))
    # Count reflects every notice ever added.
    assert container.count_for("empty_row1") == 7
    # Retention stops at max_per_type.
    assert len(container.grouped()["empty_row1"]) == 3


def test_grouped_keys_are_sorted():
    container = NoticeContainer()
    container.add(Notice("unknown_file", Severity.INFO, {}))
    container.add(Notice("empty_file", Severity.ERROR, {}))
    container.add(Notice("csv_parsing_failed", Severity.ERROR, {}))
    assert list(container.grouped()) == [
        "csv_parsing_failed2",
        "empty_file2",
        "unknown_file0",
    ]


def test_samples_keep_discovery_order():
    container = NoticeContainer()
    for row in (5, 2, 9):
        container.add(Notice("empty_row", Severity.WARNING, {"csvRowNumber": row}))
    rows = [n.context["csvRowNumber"] for n in container.grouped()["empty_row1"]]
    assert rows == [5, 2, 9]


def test_error_and_warning_flags():
    container = NoticeContainer()
    assert not container.has_errors() and not container.has_warnings()
    container.add(Notice("unknown_file", Severity.INFO, {}))
    assert not container.has_errors() and not container.has_warnings()
    container.add(Notice("empty_row", Severity.WARNING, {}))
    assert container.has_warnings() and not container.has_errors()
    container.add(Notice("empty_file", Severity.ERROR, {}))
    assert container.has_errors()


def test_merge_sums_counts_rather_than_recounting():
    # Mirrors upstream NoticeContainer.addAll. A scratch container that hit its
    # per-type cap still contributes its full total, so the report's totalNotices
    # does not undercount. Re-adding its retained notices one by one would.
    scratch = NoticeContainer(max_per_type=2)
    for index in range(5):
        scratch.add(Notice("duplicated_column", Severity.ERROR, {"index": index}))
    key = Notice("duplicated_column", Severity.ERROR, {}).mapping_key
    assert scratch.count_for(key) == 5
    assert sum(len(group) for group in scratch.grouped().values()) == 2

    main = NoticeContainer()
    main.merge(scratch)
    assert main.count_for(key) == 5
    assert sum(len(group) for group in main.grouped().values()) == 2
    assert main.has_errors()
    assert main.error_count() == 5
