"""The scan hub: one pass over a table feeding several per-row consumers."""

import datetime

from fakefeed import FakeFeed
from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity
from gtfs_validator.rules._shared.scan_hub import run_scan

CTX = Context(date=datetime.date(2026, 6, 1), country_code="")
ROWS = [{"trip_id": "T1", "_row_number": 2}, {"trip_id": "T2", "_row_number": 3}]


class Collect:
    def __init__(self, feed, ctx):
        self.seen = []

    def row(self, row):
        self.seen.append(row["trip_id"])

    def finish(self):
        for trip_id in self.seen:
            yield Notice("a_code", Severity.INFO, {"tripId": trip_id})


class Boom:
    def __init__(self, feed, ctx):
        pass

    def row(self, row):
        raise ValueError("boom")

    def finish(self):
        yield Notice("b_code", Severity.INFO, {})


class FinishBoom(Collect):
    def finish(self):
        raise ValueError("late boom")
        yield  # pragma: no cover - marks this as a generator like the real ones


def test_every_consumer_sees_every_row_from_one_pass():
    feed = FakeFeed({"stop_times.txt": ROWS})
    results = dict(run_scan(feed, CTX, "stop_times.txt", [("a", Collect), ("b", Collect)]))
    assert [n.context["tripId"] for n in results["a"].in_order()] == ["T1", "T2"]
    assert [n.context["tripId"] for n in results["b"].in_order()] == ["T1", "T2"]


def test_results_come_back_in_registration_order():
    feed = FakeFeed({"stop_times.txt": ROWS})
    results = run_scan(feed, CTX, "stop_times.txt", [("b", Collect), ("a", Collect)])
    assert [code for code, _ in results] == ["b", "a"]


def test_a_raising_consumer_is_isolated_and_reported():
    feed = FakeFeed({"stop_times.txt": ROWS})
    results = dict(run_scan(feed, CTX, "stop_times.txt", [("a", Collect), ("b", Boom)]))
    assert [n.context["tripId"] for n in results["a"].in_order()] == ["T1", "T2"]
    assert isinstance(results["b"], ValueError)


def test_a_consumer_raising_in_finish_loses_only_its_notices():
    feed = FakeFeed({"stop_times.txt": ROWS})
    results = dict(run_scan(feed, CTX, "stop_times.txt", [("a", FinishBoom), ("b", Collect)]))
    assert isinstance(results["a"], ValueError)
    assert [n.context["tripId"] for n in results["b"].in_order()] == ["T1", "T2"]


def test_an_inapplicable_factory_is_skipped():
    feed = FakeFeed({"stop_times.txt": ROWS})
    results = run_scan(feed, CTX, "stop_times.txt", [("a", lambda feed, ctx: None)])
    assert results == []


def test_a_failed_dependency_skips_every_consumer():
    # A table whose load failed silences a file rule entirely; through the hub it must
    # silence every consumer the same way, with nothing reported as a failure.
    feed = FakeFeed({"stop_times.txt": ROWS}, unindexable=frozenset({"stop_times.txt"}))
    results = run_scan(feed, CTX, "stop_times.txt", [("a", Collect)])
    assert results == []


def test_caps_apply_per_consumer_as_the_destination_would():
    class Chatty(Collect):
        def finish(self):
            for _ in range(5):
                yield Notice("a_code", Severity.INFO, {})

    feed = FakeFeed({"stop_times.txt": ROWS})
    results = dict(run_scan(feed, CTX, "stop_times.txt", [("a", Chatty)], caps=(1000, 3, 1000)))
    assert len(results["a"].in_order()) == 3
    assert results["a"].count_for("a_code0") == 5


def test_row_emissions_stream_into_the_buffer_in_order():
    # A consumer may return notices from row() itself; they are buffered as they
    # arrive, which is what keeps the hub's memory bounded on a rule that fires
    # per row. Mixed with finish() emissions, the order is rows first.
    class Stream:
        def __init__(self, feed, ctx):
            pass

        def row(self, row):
            return [Notice("s_code", Severity.INFO, {"tripId": row["trip_id"]})]

        def finish(self):
            yield Notice("s_code", Severity.INFO, {"tripId": "END"})

    feed = FakeFeed({"stop_times.txt": ROWS})
    results = dict(run_scan(feed, CTX, "stop_times.txt", [("s", Stream)]))
    assert [n.context["tripId"] for n in results["s"].in_order()] == ["T1", "T2", "END"]


def test_a_dependency_failure_in_finish_is_a_silent_skip():
    # missing_stop_times_record's finish() re-reads stop_times.txt, and
    # trip_with_shape_dist's reads shapes and trips. A failed table there is the
    # sequential DependencyFailed skip, never a runtime_exception system error.
    from gtfs_validator.rules.feedview import DependencyFailed

    class LateRead(Collect):
        def finish(self):
            raise DependencyFailed("shapes.txt")
            yield  # pragma: no cover - marks this as a generator like the real ones

    feed = FakeFeed({"stop_times.txt": ROWS})
    results = dict(run_scan(feed, CTX, "stop_times.txt", [("a", LateRead), ("b", Collect)]))
    assert "a" not in results
    assert [n.context["tripId"] for n in results["b"].in_order()] == ["T1", "T2"]


def test_a_failing_table_read_is_isolated_per_consumer():
    # Sequentially each rule's own pass would hit the same cursor error and draw
    # its own runtime_exception_in_validator_error while later rules still run.
    # The shared read failing must therefore surface one exception per live
    # consumer, never escape the hub and kill the whole file-rule stage.
    class MidReadBoom:
        def rows(self, filename):
            def generator():
                yield ROWS[0]
                raise RuntimeError("cursor died")

            return generator()

        def __init__(self):
            self.cache = {}

    feed = MidReadBoom()
    results = dict(run_scan(feed, CTX, "stop_times.txt", [("a", Collect), ("b", Collect)]))
    assert isinstance(results["a"], RuntimeError)
    assert isinstance(results["b"], RuntimeError)


def test_factory_failures_survive_a_failed_dependency():
    # A factory that raises does so before any table read, so its
    # runtime_exception_in_validator_error is owed even when the shared read
    # then finds the table unindexable and silences everyone else.
    class BadFactory:
        def __init__(self, feed, ctx):
            raise ValueError("factory boom")

    feed = FakeFeed({"stop_times.txt": ROWS}, unindexable=frozenset({"stop_times.txt"}))
    results = dict(run_scan(feed, CTX, "stop_times.txt", [("a", BadFactory), ("b", Collect)]))
    assert isinstance(results["a"], ValueError)
    assert "b" not in results
