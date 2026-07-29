"""Stage 5: stream stored rows past the rules registered for each table.

The store already holds only rows that survived typing, which is what upstream's
SingleEntityValidator sees: an entity exists for a row that parsed, and a row
that drew an ERROR was never stored. So there is no row filtering here, and a
rule that wants to reason about a failed row cannot, by design.
"""

from __future__ import annotations

from collections.abc import Mapping

from gtfs_validator.context import Context
from gtfs_validator.error_ids import AppError, CarriedFailure
from gtfs_validator.notices import Notice, NoticeContainer, Severity
from gtfs_validator.rules._shared.scan_hub import run_scan
from gtfs_validator.rules.feedview import DependencyFailed, FeedView
from gtfs_validator.rules.registry import (
    SCAN_REGISTRY,
    RuleSpec,
    entity_rules_for,
    file_rules,
    load_rules,
    scan_rules_for,
    scan_tables,
)
from gtfs_validator.store import FeedStore
from gtfs_validator.table_status import TableLoad

# Re-exported: every test and several rules import DependencyFailed from here, and the split
# that moved it next door is not a reason to touch them.
__all__ = ["DependencyFailed", "FeedView", "run_rules"]


def _applies(spec: RuleSpec, columns: frozenset[str]) -> bool:
    """shouldCallValidate: skip the rule unless the header carries one of its
    columns. An empty requirement means the rule always runs."""
    if not spec.requires_any_column:
        return True
    return any(column in columns for column in spec.requires_any_column)


def _run_scan_hubs(
    view: FeedView, ctx: Context, notices: NoticeContainer
) -> dict[str, NoticeContainer | Exception]:
    """One shared pass per scanned table, instead of one pass per rule.

    The results merge in the caller's file-rule loop at each code's own position
    in registry order, so the report is the one the per-rule passes produced;
    only the number of passes changes.
    """
    caps = (notices.max_total, notices.max_per_type, notices.max_exports_per_type)
    results: dict[str, NoticeContainer | Exception] = {}
    for table in scan_tables():
        specs = scan_rules_for(table)
        consumers = [(spec.code, spec.factory) for spec in specs]
        for code, result in run_scan(view, ctx, table, consumers, caps):
            results[code] = result
    return results


def run_rules(
    store: FeedStore,
    notices: NoticeContainer,
    ctx: Context,
    loads: Mapping[str, TableLoad],
    present: frozenset[str] | None = None,
    system_errors: NoticeContainer | None = None,
) -> None:
    """Run every applicable rule, isolating a failure the way upstream does.

    ValidatorUtil.safeValidate wraps each (validator, entity) invocation
    individually, so one rule raising on one row costs that pair and nothing
    else. Letting the exception escape instead truncates the whole pass: every
    later row and every other rule silently produce nothing, and the report
    still looks like a complete run. That is how a color helper reading the
    wrong type cost six rows of notices across two codes before the
    differential caught it.
    """
    load_rules()
    # Absent an explicit archive listing, every loaded table counts as present.
    # The CLI always passes one; the fallback keeps a focused test from having to.
    present = frozenset(loads) if present is None else present
    for filename in sorted(loads):
        if not store.has_table(filename):
            continue
        specs = [
            spec for spec in entity_rules_for(filename) if _applies(spec, loads[filename].columns)
        ]
        if not specs:
            continue
        for row in store.rows(filename):
            entity = dict(row)
            for spec in specs:
                try:
                    for notice in spec.func(entity, ctx):
                        notices.add(notice)
                except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                    _report_failure(system_errors, spec, exc)

    # File rules run after the entity pass, matching upstream's order: the
    # loader validates entities as it reads them and the multi-file validators
    # run once every table is loaded.
    view = FeedView(store, loads, present)
    # The scan hubs first: one pass per table feeds every registered consumer,
    # instead of one pass per rule.
    scan_results = _run_scan_hubs(view, ctx, notices)
    for file_spec in file_rules():
        if file_spec.code in SCAN_REGISTRY:
            result = scan_results.get(file_spec.code)
            if result is None:
                continue  # inapplicable, or a failed dependency: the skip is the behaviour
            if isinstance(result, Exception):
                _report_failure(system_errors, file_spec, result)
                continue
            notices.merge(result)
            continue
        # Buffered rather than added as they come: a rule that turns out to depend on a
        # failed table emits nothing at all, so notices from before the read it failed on
        # have to be discarded. Upstream never starts the validator in the first place.
        #
        # The buffer is a container rather than a list, so it applies the same caps on the way
        # in that the destination would. A list was unbounded in the number of notices one rule
        # emits, which made our peak worse than upstream's for no gain: upstream caps retention
        # as each notice arrives and only ever holds the capped set. `merge` is its `addAll`, so
        # counts are summed and the caps are not applied twice; `totalNotices` stays exact for a
        # rule that emits more than the cap, and the retained notices keep their order, so the
        # exported samples are the same ones either way.
        produced = NoticeContainer(
            max_total=notices.max_total,
            max_per_type=notices.max_per_type,
            max_exports_per_type=notices.max_exports_per_type,
        )
        try:
            produced.add_all(file_spec.func(view, ctx))
        except DependencyFailed:  # silent-ok - the skip *is* the behaviour, see DependencyFailed
            continue
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            _report_failure(system_errors, file_spec, exc)
            continue
        notices.merge(produced)


def _report_failure(system_errors: NoticeContainer | None, spec: RuleSpec, exc: Exception) -> None:
    """runtime_exception_in_validator_error, one per failed invocation.

    No deduplication, and no row number in the context. Upstream's safeValidate
    also wraps each (validator, entity) pair and its addSystemError appends
    unconditionally, so a rule failing on every row costs one system error per
    row on both sides. Collapsing them here would be a divergence, not a
    tidy-up; the notice caps are what bound the damage.
    """
    if system_errors is None:
        raise exc
    if isinstance(exc, CarriedFailure):
        # A worker pre-rendered both fields; see error_ids.carry.
        name, message = exc.class_name, exc.message
    else:
        name = type(exc).__name__
        message = exc.to_log_line() if isinstance(exc, AppError) else str(exc)
    system_errors.add(
        Notice(
            "runtime_exception_in_validator_error",
            Severity.ERROR,
            {
                # RuntimeExceptionInValidatorError's three fields. An AppError
                # reports through to_log_line so its stable ID survives, the same
                # way the loader's handler does.
                "validator": spec.code,
                "exception": name,
                "message": message,
            },
        )
    )
