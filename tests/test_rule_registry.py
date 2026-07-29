"""The rule registry: one module per notice code, self-registering."""

import datetime

import pytest

from gtfs_validator import manifest
from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.rules import registry
from gtfs_validator.rules.runner import run_rules
from gtfs_validator.schema import load_schemas
from gtfs_validator.store import FeedStore
from gtfs_validator.table_status import TableLoad, TableStatus


def test_a_decorated_function_registers_under_its_code():
    @registry.rule(code="fake_code", severity=Severity.WARNING, filename="routes.txt")
    def check(row, ctx):
        return ()

    spec = registry.REGISTRY["fake_code"]
    assert spec.severity is Severity.WARNING
    assert spec.filename == "routes.txt"
    assert spec.func is check
    del registry.REGISTRY["fake_code"]


def test_registering_a_code_twice_is_an_error():
    @registry.rule(code="dupe_code", severity=Severity.ERROR, filename="routes.txt")
    def first(row, ctx):
        return ()

    with pytest.raises(ValueError, match="dupe_code"):

        @registry.rule(code="dupe_code", severity=Severity.ERROR, filename="routes.txt")
        def second(row, ctx):
            return ()

    del registry.REGISTRY["dupe_code"]


def test_context_carries_the_date_and_country_code():
    ctx = Context(date=datetime.date(2026, 7, 24), country_code="US")
    assert ctx.date == datetime.date(2026, 7, 24)
    assert ctx.country_code == "US"


def _loads(columns_by_file):
    """A TableLoad per table, carrying its declared columns and a clean status."""
    return {name: TableLoad(columns=columns) for name, columns in columns_by_file.items()}


def _ctx():
    return Context(date=datetime.date(2026, 7, 24), country_code="US")


def _store_with(tmp_path, filename, rows):
    """A store holding one table, built through the real schema so the column
    types match what the typing stage would have produced."""
    store = FeedStore.open(tmp_path / "feed.db")
    schema = load_schemas()[filename]
    store.create_table(schema)
    store.insert_rows(schema, [{**row, "_row_number": i + 2} for i, row in enumerate(rows)])
    return store


def test_the_runner_streams_rows_past_a_registered_rule(tmp_path):
    seen = []

    @registry.rule(code="probe_code", severity=Severity.WARNING, filename="routes.txt")
    def check(row, ctx):
        seen.append(row["route_id"])
        yield Notice("probe_code", Severity.WARNING, {"routeId": row["route_id"]})

    notices = NoticeContainer()
    store = _store_with(tmp_path, "routes.txt", [{"route_id": "R1"}, {"route_id": "R2"}])
    run_rules(store, notices, _ctx(), loads=_loads({"routes.txt": frozenset({"route_id"})}))

    assert seen == ["R1", "R2"]
    assert notices.count_for(Notice("probe_code", Severity.WARNING).mapping_key) == 2
    del registry.REGISTRY["probe_code"]


def test_a_rule_is_skipped_when_the_header_lacks_every_required_column(tmp_path):
    # shouldCallValidate is a header test: the rule does not run at all, which is
    # not the same as running and finding nothing.
    ran = []

    @registry.rule(
        code="gated_code",
        severity=Severity.WARNING,
        filename="routes.txt",
        requires_any_column=("route_color", "route_text_color"),
    )
    def check(row, ctx):
        ran.append(row)
        return ()

    notices = NoticeContainer()
    store = _store_with(tmp_path, "routes.txt", [{"route_id": "R1"}])
    run_rules(store, notices, _ctx(), loads=_loads({"routes.txt": frozenset({"route_id"})}))
    assert ran == []

    run_rules(store, notices, _ctx(), loads=_loads({"routes.txt": frozenset({"route_color"})}))
    assert len(ran) == 1
    del registry.REGISTRY["gated_code"]


def test_every_registered_rule_declares_a_real_notice_code():
    unknown = manifest.registered_codes() - manifest.load_manifest().codes
    assert unknown == frozenset(), f"registered under codes upstream does not define: {unknown}"


def test_every_registered_rule_is_listed_as_implemented():
    missing = manifest.registered_codes() - manifest.IMPLEMENTED
    assert missing == frozenset(), f"registered but not in IMPLEMENTED: {missing}"


def test_a_rule_that_raises_costs_only_that_row(tmp_path):
    # ValidatorUtil.safeValidate wraps each (validator, entity) invocation, so a
    # rule that blows up on one row does not stop the others or the remaining
    # rows. Letting it escape truncated a whole pass while still writing a report
    # that looked complete.
    @registry.rule(code="boom_code", severity=Severity.WARNING, filename="routes.txt")
    def boom(row, ctx):
        if row["route_id"] == "R2":
            raise ValueError("bang")
        yield Notice("boom_code", Severity.WARNING, {"routeId": row["route_id"]})

    notices = NoticeContainer()
    system_errors = NoticeContainer()
    store = _store_with(
        tmp_path, "routes.txt", [{"route_id": "R1"}, {"route_id": "R2"}, {"route_id": "R3"}]
    )
    run_rules(
        store,
        notices,
        _ctx(),
        loads=_loads({"routes.txt": frozenset({"route_id"})}),
        system_errors=system_errors,
    )

    assert notices.count_for(Notice("boom_code", Severity.WARNING).mapping_key) == 2
    failures = system_errors.grouped()[
        Notice("runtime_exception_in_validator_error", Severity.ERROR).mapping_key
    ]
    assert failures[0].context == {
        "validator": "boom_code",
        "exception": "ValueError",
        "message": "bang",
    }
    del registry.REGISTRY["boom_code"]


def test_a_file_rule_runs_once_and_sees_the_whole_table(tmp_path):
    seen = []

    @registry.file_rule(code="whole_file_code", severity=Severity.WARNING)
    def check(feed, ctx):
        seen.append([row["route_id"] for row in feed.rows("routes.txt")])
        yield Notice("whole_file_code", Severity.WARNING, {})

    notices = NoticeContainer()
    store = _store_with(tmp_path, "routes.txt", [{"route_id": "R1"}, {"route_id": "R2"}])
    run_rules(store, notices, _ctx(), loads=_loads({"routes.txt": frozenset({"route_id"})}))

    assert seen == [["R1", "R2"]]
    assert notices.count_for(Notice("whole_file_code", Severity.WARNING).mapping_key) == 1
    del registry.FILE_REGISTRY["whole_file_code"]


def test_a_file_rule_distinguishes_a_missing_table_from_an_empty_one(tmp_path):
    verdicts = {}

    @registry.file_rule(code="presence_code", severity=Severity.WARNING)
    def check(feed, ctx):
        verdicts["calendar"] = feed.is_missing("calendar.txt")
        verdicts["routes"] = feed.is_missing("routes.txt")
        return ()

    notices = NoticeContainer()
    store = _store_with(tmp_path, "routes.txt", [])
    run_rules(store, notices, _ctx(), loads=_loads({"routes.txt": frozenset({"route_id"})}))

    # routes.txt was in the archive and simply has no rows; calendar.txt was not
    # there at all. Upstream keeps MISSING_FILE and EMPTY_FILE distinct and
    # missing_calendar_and_calendar_date_files fires on the first only.
    assert verdicts == {"calendar": True, "routes": False}
    del registry.FILE_REGISTRY["presence_code"]


def test_a_failing_file_rule_is_isolated_like_an_entity_rule(tmp_path):
    @registry.file_rule(code="boom_file_code", severity=Severity.WARNING)
    def boom(feed, ctx):
        raise ValueError("bang")
        yield  # pragma: no cover - unreachable, keeps this a generator

    notices = NoticeContainer()
    system_errors = NoticeContainer()
    store = _store_with(tmp_path, "routes.txt", [{"route_id": "R1"}])
    run_rules(
        store,
        notices,
        _ctx(),
        loads=_loads({"routes.txt": frozenset({"route_id"})}),
        system_errors=system_errors,
    )
    failures = system_errors.grouped()[
        Notice("runtime_exception_in_validator_error", Severity.ERROR).mapping_key
    ]
    assert failures[0].context["validator"] == "boom_file_code"
    del registry.FILE_REGISTRY["boom_file_code"]


def test_a_code_cannot_be_both_an_entity_and_a_file_rule():
    @registry.rule(code="both_code", severity=Severity.WARNING, filename="routes.txt")
    def entity(row, ctx):
        return ()

    with pytest.raises(ValueError, match="both_code"):

        @registry.file_rule(code="both_code", severity=Severity.WARNING)
        def whole(feed, ctx):
            return ()

    del registry.REGISTRY["both_code"]


def test_a_file_rule_is_skipped_when_a_table_it_reads_failed_to_parse(tmp_path):
    # A row failing parse marks the whole TableLoad UNPARSABLE_ROWS, and upstream then skips
    # every FileValidator that container is injected into. Measured twice, and the second
    # measurement corrected the first: on a calendar.txt whose second row is short and whose
    # first has every day off, the jar reports only invalid_row_length, which handing the
    # rule an empty table also achieved. But an empty table is not the same as no validator:
    # with stop_times.txt absent, an empty table made four rules report every trip and every
    # stop, where the jar reports none of them. So reading a failed table raises, and the
    # runner drops whatever the rule had produced.
    seen = []

    @registry.file_rule(code="failed_table_code", severity=Severity.WARNING)
    def check(feed, ctx):
        yield Notice("failed_table_code", Severity.WARNING, {"before": "the read"})
        seen.append([row["route_id"] for row in feed.rows("routes.txt")])

    notices = NoticeContainer()
    store = _store_with(tmp_path, "routes.txt", [{"route_id": "R1"}])
    failed = TableLoad(columns=frozenset({"route_id"}))
    failed.fail(TableStatus.UNPARSABLE_ROWS)
    run_rules(store, notices, _ctx(), loads={"routes.txt": failed})
    # The rule never got past the read, and the notice it had already yielded is gone.
    assert seen == []
    assert notices.count_for("failed_table_code") == 0
    del registry.FILE_REGISTRY["failed_table_code"]


def test_a_file_rule_still_runs_against_a_valid_empty_table(tmp_path):
    # The gate is on status, not emptiness: a header-only table is valid and its rule runs.
    # Measured on a feed whose stop_times.txt is just a header, where the jar reports every
    # trip unused.
    seen = []

    @registry.file_rule(code="empty_table_code", severity=Severity.WARNING)
    def check(feed, ctx):
        seen.append([row["route_id"] for row in feed.rows("routes.txt")])
        return ()

    notices = NoticeContainer()
    store = _store_with(tmp_path, "routes.txt", [])
    run_rules(
        store,
        notices,
        _ctx(),
        loads={"routes.txt": TableLoad(columns=frozenset({"route_id"}))},
    )
    assert seen == [[]]
    del registry.FILE_REGISTRY["empty_table_code"]


def test_a_table_that_failed_to_load_is_still_present(tmp_path):
    # A file that raised during loading is dropped from `loads`, but the archive
    # still contains it, so is_missing must be false. Measured: a feed whose
    # calendar.txt is present but undecodable draws no
    # missing_calendar_and_calendar_date_files from the jar, and drew one from us.
    verdicts = {}

    @registry.file_rule(code="still_present_code", severity=Severity.WARNING)
    def check(feed, ctx):
        verdicts["calendar"] = feed.is_missing("calendar.txt")
        verdicts["absent"] = feed.is_missing("frequencies.txt")
        return ()

    notices = NoticeContainer()
    store = _store_with(tmp_path, "routes.txt", [{"route_id": "R1"}])
    run_rules(
        store,
        notices,
        _ctx(),
        loads=_loads({"routes.txt": frozenset({"route_id"})}),
        present=frozenset({"routes.txt", "calendar.txt"}),
    )
    assert verdicts == {"calendar": False, "absent": True}
    del registry.FILE_REGISTRY["still_present_code"]


def test_every_registered_rule_declares_the_manifest_severity():
    """The decorator's `severity=` is metadata: nothing reads it at runtime, and the notices a
    rule yields carry their own. So a rule can declare one severity and emit another, and until
    this test nothing compared either of them to the generated manifest.

    Found while checking that a presence test could fail: patching a rule's decorator severity
    broke no test at all. Patching the *emitted* one does, in
    tests/test_rules_field_presence.py, but only for the six rules named there. This covers all
    of them in the one direction a static check can.
    """
    from gtfs_validator.manifest import load_manifest

    manifest = load_manifest()
    registry.load_rules()
    specs = {**registry.REGISTRY, **registry.FILE_REGISTRY}
    assert specs
    mismatched = {
        code: (spec.severity.name, manifest.severity_of(code).name)
        for code, spec in specs.items()
        if spec.severity is not manifest.severity_of(code)
    }
    assert mismatched == {}
