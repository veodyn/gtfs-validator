import json
import zipfile

from gtfs_validator.cli import EXIT_OK, EXIT_USAGE, main


def make_feed(tmp_path):
    """A feed conformant enough that no ERROR fires, plus two deliberate faults.

    Every required column is present and every value parses, so the only notices
    are the missing feed_info.txt (WARNING) and the stray notes.md (INFO). Since
    plan 2 wired up field typing, a skeletal feed of bare id columns draws
    missing_required_field and is no longer usable as the quiet case.
    """
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
        zf.writestr("notes.md", "hello")
    return path


def test_end_to_end_writes_both_reports(tmp_path):
    out = tmp_path / "out"
    code = main(["-i", str(make_feed(tmp_path)), "-o", str(out)])
    report = json.loads((out / "report.json").read_text())
    assert (out / "system_errors.json").exists()
    codes = [n["code"] for n in report["notices"]]
    assert "unknown_file" in codes
    assert "missing_recommended_file" in codes
    assert code == 0


def error_bearing_feed(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("agency.txt", "agency_name\nAcme\n")
    return path


def test_error_notices_alone_exit_zero_like_upstream(tmp_path):
    # Measured against the v8.0.1 jar: it exits 0 on this feed despite four
    # ERROR notices, reserving a nonzero status for a runner failure. Swapping
    # the binary must not change a pipeline's exit status.
    out = tmp_path / "out"
    assert main(["-i", str(error_bearing_feed(tmp_path)), "-o", str(out)]) == 0
    codes = [n["code"] for n in json.loads((out / "report.json").read_text())["notices"]]
    assert "missing_required_file" in codes


def test_fail_on_error_opts_into_lint_style_exit(tmp_path):
    out = tmp_path / "out"
    argv = ["-i", str(error_bearing_feed(tmp_path)), "-o", str(out), "--fail-on-error"]
    assert main(argv) == 1


def test_fail_on_error_stays_zero_when_only_warnings_fire(tmp_path):
    out = tmp_path / "out"
    argv = ["-i", str(make_feed(tmp_path)), "-o", str(out), "--fail-on-error"]
    assert main(argv) == 0


def test_report_notices_are_sorted(tmp_path):
    out = tmp_path / "out"
    main(["-i", str(make_feed(tmp_path)), "-o", str(out)])
    codes = [n["code"] for n in json.loads((out / "report.json").read_text())["notices"]]
    assert codes == sorted(codes)


def test_typed_notices_reach_the_report(tmp_path):
    path = tmp_path / "feed.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "agency.txt",
            "agency_id,agency_name,agency_url,agency_timezone\n1,Acme,not-a-url,Mars/Olympus\n",
        )
    out = tmp_path / "out"
    main(["-i", str(path), "-o", str(out)])
    codes = [n["code"] for n in json.loads((out / "report.json").read_text())["notices"]]
    assert "invalid_url" in codes
    assert "invalid_timezone" in codes


def test_duplicate_primary_key_reaches_the_report(tmp_path):
    path = tmp_path / "feed.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "stops.txt", "stop_id,stop_name,stop_lat,stop_lon\nS1,A,1.0,2.0\nS1,B,3.0,4.0\n"
        )
    out = tmp_path / "out"
    main(["-i", str(path), "-o", str(out)])
    codes = [n["code"] for n in json.loads((out / "report.json").read_text())["notices"]]
    assert "duplicate_key" in codes


def test_country_code_turns_phone_validation_on(tmp_path):
    path = tmp_path / "feed.zip"
    body = (
        "agency_id,agency_name,agency_url,agency_timezone,agency_phone\n"
        "1,Acme,https://example.com,America/New_York,123\n"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("agency.txt", body)

    quiet = tmp_path / "quiet"
    main(["-i", str(path), "-o", str(quiet)])
    quiet_codes = [n["code"] for n in json.loads((quiet / "report.json").read_text())["notices"]]
    assert "invalid_phone_number" not in quiet_codes

    loud = tmp_path / "loud"
    main(["-i", str(path), "-o", str(loud), "-c", "US"])
    loud_codes = [n["code"] for n in json.loads((loud / "report.json").read_text())["notices"]]
    assert "invalid_phone_number" in loud_codes


def test_unreadable_feed_still_writes_both_reports(tmp_path):
    # A missing or truncated archive is a runtime failure, not a validation
    # finding. It belongs in system_errors.json, and both reports must exist.
    out = tmp_path / "out"
    code = main(["-i", str(tmp_path / "does-not-exist.zip"), "-o", str(out)])
    assert (out / "report.json").exists()
    errors = json.loads((out / "system_errors.json").read_text())["notices"]
    assert errors[0]["code"] == "runtime_exception_in_loader_error"
    assert code != 0


def test_truncated_zip_is_reported_not_raised(tmp_path):
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"PK\x03\x04 not really a zip")
    out = tmp_path / "out"
    main(["-i", str(broken), "-o", str(out)])
    errors = json.loads((out / "system_errors.json").read_text())["notices"]
    assert errors[0]["code"] == "runtime_exception_in_loader_error"


def test_report_is_written_as_utf8_regardless_of_locale(tmp_path):
    path = tmp_path / "feed.zip"
    with zipfile.ZipFile(path, "w") as zf:
        # A non-ASCII filename reaches the report through unknown_file's context.
        zf.writestr("agency.txt", "agency_name\nAcme\n")
        zf.writestr("駅名.txt", "x\n")
    out = tmp_path / "out"
    main(["-i", str(path), "-o", str(out)])
    raw = (out / "report.json").read_bytes()
    assert "駅名.txt" in raw.decode("utf-8")


def feed_with(tmp_path, name, overrides):
    """The clean feed with some files replaced, for whole-table status tests."""
    base = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n"
        "1,Acme Transit,https://example.com,America/New_York\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nS1,Main St,40.7,-74.0\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_type\nR1,1,10,3\n",
        "trips.txt": "route_id,service_id,trip_id\nR1,WEEK,T1\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,08:00:00,08:00:00,S1,1\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,"
        "sunday,start_date,end_date\nWEEK,1,1,1,1,1,0,0,20260101,20261231\n",
    }
    base.update(overrides)
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        for filename, text in base.items():
            zf.writestr(filename, text)
    return path


def report_codes(tmp_path, feed, out_name):
    out = tmp_path / out_name
    main(["-i", str(feed), "-o", str(out)])
    report = json.loads((out / "report.json").read_text())
    return {notice["code"] for notice in report["notices"]}


DUPLICATE_STOPS = "stop_id,stop_name,stop_lat,stop_lon\nS1,A,40.7,-74.0\nS1,B,41.0,-74.0\n"


def test_duplicate_key_fires_when_every_row_parses(tmp_path):
    feed = feed_with(tmp_path, "dupes.zip", {"stops.txt": DUPLICATE_STOPS})
    assert "duplicate_key" in report_codes(tmp_path, feed, "dupes")


def test_one_unparsable_row_suppresses_duplicate_key_for_the_whole_table(tmp_path):
    # Measured against the jar: adding a row with an unparsable stop_lat to the
    # feed above leaves invalid_float as the only notice. Upstream marks the table
    # UNPARSABLE_ROWS and never builds its indices, so the two clean duplicate
    # rows are never compared.
    feed = feed_with(
        tmp_path,
        "dupes-bad.zip",
        {"stops.txt": DUPLICATE_STOPS + "S2,C,notanumber,-74.0\n"},
    )
    codes = report_codes(tmp_path, feed, "dupes-bad")
    assert "invalid_float" in codes
    assert "duplicate_key" not in codes


def test_header_errors_stop_the_file_before_any_row_is_read(tmp_path):
    # agency.txt missing two required columns, with a lowercase agency_name that
    # would otherwise draw mixed_case_recommended_field. Measured against the jar:
    # only the two missing_required_column notices are reported, because
    # TableStatus.INVALID_HEADERS means "the other rows were not scanned".
    feed = feed_with(
        tmp_path, "bad-header.zip", {"agency.txt": "agency_id,agency_name\n1,agency\n"}
    )
    codes = report_codes(tmp_path, feed, "bad-header")
    assert "missing_required_column" in codes
    assert "mixed_case_recommended_field" not in codes


def test_a_loader_failure_keeps_its_stable_error_id(tmp_path):
    # An unrenderable decimal raises AppError(TYPE_DECIMAL_UNRENDERABLE). The
    # registry exists so every failure is greppable by ID, and the handler
    # serialised only str(exc), so E_TYPE_001 and its context were being dropped
    # at the one place they matter. The ID goes inside message rather than into a
    # fourth key, because RuntimeExceptionInLoaderError carries exactly three.
    feed = make_feed(tmp_path)
    with zipfile.ZipFile(feed, "a") as zf:
        zf.writestr("fare_products.txt", "fare_product_id,amount,currency\nP1,1e-2147483647,USD\n")
    out = tmp_path / "out"
    main(["-i", str(feed), "-o", str(out)])
    errors = json.loads((out / "system_errors.json").read_text())["notices"]
    sample = errors[0]["sampleNotices"][0]
    assert set(sample) == {"filename", "exception", "message"}
    assert sample["filename"] == "fare_products.txt"
    assert "E_TYPE_001" in sample["message"]
    assert "exponent=-2147483647" in sample["message"]


def test_an_unparseable_date_flag_is_a_usage_error(tmp_path):
    # Upstream parses -d with DateTimeFormatter.ISO_LOCAL_DATE. Measured: the jar
    # accepts "2026-06-01" and dies on "20260601" with a DateTimeParseException,
    # so the eight-digit form the feeds themselves use is not accepted here
    # either. The CLI mirrors upstream's interface.
    feed = make_feed(tmp_path)
    assert main(["-i", str(feed), "-o", str(tmp_path / "o"), "--date", "20260601"]) == EXIT_USAGE


def test_the_date_flag_is_accepted_in_iso_form(tmp_path):
    feed = make_feed(tmp_path)
    assert main(["-i", str(feed), "-o", str(tmp_path / "o2"), "-d", "2026-06-01"]) == EXIT_OK


def test_an_iso_week_date_is_also_rejected(tmp_path):
    # date.fromisoformat accepts week dates since 3.11 and Java's ISO_LOCAL_DATE
    # does not, so the parse has to be strptime rather than fromisoformat.
    feed = make_feed(tmp_path)
    assert main(["-i", str(feed), "-o", str(tmp_path / "o3"), "-d", "2026-W23-1"]) == EXIT_USAGE


def test_a_non_zero_padded_date_is_rejected(tmp_path):
    # strptime accepts "2026-6-1" and Java's ISO_LOCAL_DATE does not. Measured:
    # the jar dies on it with a DateTimeParseException, so accepting it would make
    # our CLI take input the jar refuses.
    feed = make_feed(tmp_path)
    assert main(["-i", str(feed), "-o", str(tmp_path / "o"), "-d", "2026-6-1"]) == EXIT_USAGE


def test_an_empty_date_is_rejected_rather_than_ignored(tmp_path):
    # An explicitly empty value is a malformed date, not an omitted flag.
    feed = make_feed(tmp_path)
    assert main(["-i", str(feed), "-o", str(tmp_path / "o2"), "-d", ""]) == EXIT_USAGE


def test_threads_flag_parses_and_defaults_to_one(tmp_path):
    """Upstream's -t/--threads. The default of 1 is the sequential path unchanged;
    the flag exists for CLI parity even before any parallel stage lands."""
    from gtfs_validator.cli import parse_args

    assert parse_args(["-i", "x.zip"]).threads == 1
    assert parse_args(["-t", "4", "-i", "x.zip"]).threads == 4
    assert parse_args(["--threads", "2", "-i", "x.zip"]).threads == 2
