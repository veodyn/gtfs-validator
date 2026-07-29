"""Parallel loading must be invisible: byte-identical reports at any thread count.

The merge rules under test: tables load in workers but their notices re-enter the
one real container in canonical file-visit order through `add`, so the global caps
and counts replay exactly; a table whose loader raises surfaces as the same system
error in the same position; and the store ends up with the same rows.
"""

from __future__ import annotations

import json
import zipfile

from gtfs_validator.cli import main


def _messy_feed(path):
    """A small feed with notices spread across several tables, plus stray content."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "agency.txt",
            "agency_id,agency_name,agency_url,agency_timezone\n"
            "A1,Transit,http://example.com,America/New_York\n",
        )
        archive.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon\nS1,ALL CAPS STOP,91.0,-72.0\nS2,,40.7,-72.1\n",
        )
        archive.writestr(
            "routes.txt",
            "route_id,agency_id,route_short_name,route_long_name,route_type\nR1,A1,1,Main,99\n",
        )
        archive.writestr(
            "trips.txt",
            "route_id,service_id,trip_id\nR1,C1,T1\n",
        )
        archive.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,bad-time,08:10:00,S2,2\n",
        )
        archive.writestr(
            "calendar.txt",
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,"
            "start_date,end_date\nC1,1,1,1,1,1,0,0,20260101,20261231\n",
        )
        archive.writestr("stray.txt", "a,b\n1,2\n")


def _reports(out):
    """Both reports, with the summary fields that differ between runs removed.

    `report.json` gained a `summary` carrying a wall clock, an elapsed time and a
    memory reading, so two runs of the same feed are no longer byte-identical and
    never can be. The notices and every deterministic summary field still are,
    and that is what these tests are about. `summary.normalise` owns the list so
    it cannot quietly grow here.
    """
    from gtfs_validator.summary import normalise

    report = normalise(json.loads((out / "report.json").read_text()))
    # `threads` is dropped here and *not* in `normalise`, because it is not
    # run-dependent: two runs at the same thread count agree on it, and it is
    # only these tests that deliberately vary it. Putting it in the shared list
    # would stop the differential noticing a report that lies about its own
    # thread count.
    report["summary"].pop("threads", None)
    return (json.dumps(report, sort_keys=True), (out / "system_errors.json").read_bytes())


def _run(feed, out, threads):
    status = main(["-i", str(feed), "-o", str(out), "-d", "2026-07-27", "-t", str(threads)])
    assert status == 0
    return _reports(out)


def test_reports_are_byte_identical_across_thread_counts(tmp_path):
    feed = tmp_path / "feed.zip"
    _messy_feed(feed)
    one = _run(feed, tmp_path / "one", 1)
    two = _run(feed, tmp_path / "two", 2)
    eight = _run(feed, tmp_path / "eight", 8)
    assert one == two
    assert one == eight
    # and the run genuinely found notices to disagree about
    assert len(json.loads(one[0])["notices"]) > 3


def test_duplicate_zip_entries_fall_back_to_the_sequential_path(tmp_path):
    """A review measured the parallel loader misattributing the loader error a
    duplicate entry causes; such an archive now takes the sequential path, so the
    reports stay byte-identical."""
    feed = tmp_path / "dup.zip"
    _messy_feed(feed)
    with zipfile.ZipFile(feed, "a") as archive:
        archive.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\nS9,Extra,1.0,1.0\n")
    one = _run_any(feed, tmp_path / "one", 1)
    two = _run_any(feed, tmp_path / "two", 2)
    assert one == two


def _run_any(feed, out, threads):
    main(["-i", str(feed), "-o", str(out), "-d", "2026-07-27", "-t", str(threads)])
    return _reports(out)


def test_carried_failures_survive_pickling_where_app_errors_do_not():
    """A worker's AppError crashed the pool's result handler: its __init__ takes an
    ErrorIds plus message while Exception.args holds only the message, so pickle's
    default reconstruction fails and the run hangs. `carry` pre-renders the two
    fields the system-error notices need into a picklable stand-in."""
    import pickle

    from gtfs_validator.error_ids import AppError, ErrorIds, carry

    original = AppError(next(iter(ErrorIds)), "boom", {"key": "value"})
    # Trusted round-trip: this is the pool's own transport, not untrusted input.
    carried = pickle.loads(pickle.dumps(carry(original)))  # noqa: S301
    assert carried.class_name == "AppError"
    assert carried.message == original.to_log_line()


def test_merge_emitted_notices_keep_their_counts_past_the_cap(tmp_path):
    """The review's reproduction: header notices reach the container through
    `merge`, which deliberately bypasses the caps, so a count one past the
    per-type cap distinguishes op replay from notice replay."""
    from gtfs_validator.notices import MAX_NOTICES_PER_TYPE

    columns = ",".join(f"x{i}" for i in range(MAX_NOTICES_PER_TYPE + 1))
    feed = tmp_path / "wide.zip"
    with zipfile.ZipFile(feed, "w") as archive:
        archive.writestr("agency.txt", "agency_name,agency_url,agency_timezone," + columns + "\n")
        archive.writestr("stops.txt", "stop_id\nS1\n")
    counts = []
    for threads, out in ((1, "one"), (2, "two")):
        main(["-i", str(feed), "-o", str(tmp_path / out), "-d", "2026-07-27", "-t", str(threads)])
        report = json.loads((tmp_path / out / "report.json").read_bytes())
        counts.append(
            next(n["totalNotices"] for n in report["notices"] if n["code"] == "unknown_column")
        )
    assert counts[0] == counts[1] == MAX_NOTICES_PER_TYPE + 1


def test_the_recording_container_retains_no_notices_of_its_own():
    # The base container is uncapped so its bookkeeping is exact, but retention
    # is the ops list's job: a pathological table emitting one notice per row
    # must not also hold every Notice object in the worker's _notices. Review
    # finding on plan 13, present since plan 11.
    from gtfs_validator.notices import Notice, Severity
    from gtfs_validator.parallel_load import _RecordingContainer

    container = _RecordingContainer((1000, 2))
    for row in range(5):
        container.add(Notice("code", Severity.WARNING, {"csvRowNumber": row}))
    assert container._notices == []
    assert container.count_for("code1") == 5
    assert len([op for op in container.ops if op[0] == "add"]) == 2


def test_unretainable_adds_aggregate_into_one_counts_op():
    # Past the destination cap, per-notice ("count", ...) ops made worker memory
    # linear in dropped notices; they aggregate per key into one mutable op.
    from gtfs_validator.notices import Notice, NoticeContainer, Severity
    from gtfs_validator.parallel_load import _RecordingContainer, _replay

    container = _RecordingContainer((1000, 2))
    for row in range(7):
        container.add(Notice("code", Severity.ERROR, {"csvRowNumber": row}))
    kinds = [op[0] for op in container.ops]
    assert kinds == ["add", "add", "counts"]
    destination = NoticeContainer()
    _replay(destination, container.ops)
    assert destination.count_for("code2") == 7
    assert destination.error_count() == 7
    assert len(destination.in_order()) == 2


def test_a_split_worker_setup_failure_is_carried_not_raised():
    # open_feed and the scratch store open before the per-table guard; a failure
    # there must come back as a share result so _absorb_shares can fall back to
    # the sequential reload, never escape through pool.starmap.
    from gtfs_validator.split_load import split_worker

    load, tagged, failure = split_worker(
        "/nonexistent/feed.zip", "stop_times.txt", 2, 0, "/nonexistent/dir/w.db", "", (10, 10)
    )
    assert load is None
    assert tagged == []
    assert failure is not None
