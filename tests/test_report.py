import json

from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.report import build_report, build_system_errors, write_json


def test_report_shape_matches_upstream():
    container = NoticeContainer()
    container.add(Notice("empty_file", Severity.ERROR, {"filename": "stops.txt"}))
    report = build_report(container)
    assert report == {
        "notices": [
            {
                "code": "empty_file",
                "severity": "ERROR",
                "totalNotices": 1,
                "sampleNotices": [{"filename": "stops.txt"}],
            }
        ]
    }


def test_total_notices_exceeds_sample_count_when_capped():
    container = NoticeContainer(max_exports_per_type=2)
    for i in range(5):
        container.add(Notice("empty_row", Severity.WARNING, {"csvRowNumber": i}))
    entry = build_report(container)["notices"][0]
    assert entry["totalNotices"] == 5
    assert len(entry["sampleNotices"]) == 2
    assert entry["sampleNotices"] == [{"csvRowNumber": 0}, {"csvRowNumber": 1}]


def test_notices_are_sorted_by_code_then_severity():
    container = NoticeContainer()
    container.add(Notice("unknown_file", Severity.INFO, {}))
    container.add(Notice("csv_parsing_failed", Severity.ERROR, {}))
    container.add(Notice("empty_row", Severity.WARNING, {}))
    codes = [n["code"] for n in build_report(container)["notices"]]
    assert codes == ["csv_parsing_failed", "empty_row", "unknown_file"]


def test_system_errors_use_their_own_document():
    container = NoticeContainer()
    container.add(Notice("runtime_exception_in_loader_error", Severity.ERROR, {"message": "boom"}))
    assert build_system_errors(container)["notices"][0]["code"] == (
        "runtime_exception_in_loader_error"
    )


def test_write_json_is_deterministic(tmp_path):
    path = tmp_path / "report.json"
    write_json({"notices": []}, path)
    assert json.loads(path.read_text()) == {"notices": []}
    assert path.read_text().endswith("\n")


def test_a_null_context_value_is_omitted_rather_than_written_as_null():
    # Upstream's Gson is built without serializeNulls, so a notice field holding
    # null is absent from the JSON rather than present as null. Measured on a
    # transfers.txt whose composite key is entirely blank: the jar's sample
    # carries fieldName1 and omits fieldValue1.
    container = NoticeContainer()
    container.add(
        Notice(
            "duplicate_key",
            Severity.ERROR,
            {"filename": "transfers.txt", "fieldName1": "", "fieldValue1": None},
        )
    )
    sample = build_report(container)["notices"][0]["sampleNotices"][0]
    assert sample == {"filename": "transfers.txt", "fieldName1": ""}
