"""One module per notice code, registered by decorator at import time.

A rule that is never imported is never registered, which would be a silent gap
rather than a failure. load_rules walks the package so that importing the
registry is enough, and the manifest test turns any remaining gap into a red
build naming the code.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, Severity

EntityRule = Callable[[dict, Context], Iterable[Notice]]
# A file rule takes the read surface defined in runner.FeedView. Annotated
# loosely to keep the registry from importing the runner, which imports it.
FileRule = Callable[[object, Context], Iterable[Notice]]

# The engine's own modules live in the rules package but register nothing.
_ENGINE_MODULES = frozenset({"registry", "runner"})


@dataclass(frozen=True)
class RuleSpec:
    code: str
    severity: Severity
    filename: str
    func: EntityRule
    requires_any_column: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileRuleSpec:
    code: str
    severity: Severity
    func: FileRule


@dataclass(frozen=True)
class ScanSpec:
    """A file rule's shared-scan participation: its factory and the table it reads.

    Every scan rule is also an ordinary file rule (its `check` delegates through
    the same consumer), so this registry adds capability rather than claiming the
    code: the manifest gate keeps reading FILE_REGISTRY.
    """

    code: str
    table: str
    factory: Callable


REGISTRY: dict[str, RuleSpec] = {}
FILE_REGISTRY: dict[str, FileRuleSpec] = {}
SCAN_REGISTRY: dict[str, ScanSpec] = {}


def _claim(code: str) -> None:
    """One code, one rule, whichever registry it lands in."""
    if code in REGISTRY or code in FILE_REGISTRY:
        raise ValueError(f"duplicate rule registration for {code}")


def rule(
    *,
    code: str,
    severity: Severity,
    filename: str,
    requires_any_column: Iterable[str] = (),
) -> Callable[[EntityRule], EntityRule]:
    """Register one rule against one notice code.

    requires_any_column mirrors upstream's shouldCallValidate: the rule is
    skipped outright unless the table's header carries at least one of these
    columns. That is a header test, not a value test, so a present-but-empty
    cell still runs the rule.
    """

    def register(func: EntityRule) -> EntityRule:
        _claim(code)
        REGISTRY[code] = RuleSpec(
            code=code,
            severity=severity,
            filename=filename,
            func=func,
            requires_any_column=tuple(requires_any_column),
        )
        return func

    return register


def file_rule(*, code: str, severity: Severity) -> Callable[[FileRule], FileRule]:
    """Register a rule that sees the whole feed once, as a FileValidator does.

    No filename and no column precondition: a file rule chooses its own tables,
    and several of them fire precisely because a table is absent, so gating one
    on a header it never reads would suppress it.
    """

    def register(func: FileRule) -> FileRule:
        _claim(code)
        FILE_REGISTRY[code] = FileRuleSpec(code=code, severity=severity, func=func)
        return func

    return register


def scan_rule(*, code: str, table: str) -> Callable:
    """Register a file rule's scan factory for the shared pass over `table`.

    Applied to the module's `scan(feed, ctx)` function, beside the `@file_rule`
    on its `check`. Duplicate scan registration for a code is the same mistake
    duplicate rule registration is.
    """

    def register(factory: Callable) -> Callable:
        if code in SCAN_REGISTRY:
            raise ValueError(f"duplicate scan registration for {code}")
        SCAN_REGISTRY[code] = ScanSpec(code=code, table=table, factory=factory)
        return factory

    return register


def scan_rules_for(table: str) -> list[ScanSpec]:
    """The scan specs for one table, in registration order, which is registry order."""
    return [spec for spec in SCAN_REGISTRY.values() if spec.table == table]


def scan_tables() -> list[str]:
    """Every table with at least one scan rule, in first-registration order."""
    seen: dict[str, None] = {}
    for spec in SCAN_REGISTRY.values():
        seen.setdefault(spec.table)
    return list(seen)


def file_rules() -> list[FileRuleSpec]:
    return list(FILE_REGISTRY.values())


def load_rules() -> dict[str, RuleSpec | FileRuleSpec]:
    """Import every rule module so the decorators run, then return both registries.

    Both, not just the entity one: the manifest gate reads this, and returning
    half of it would silently stop covering the file rules.
    """
    package = importlib.import_module(__package__)
    for module in pkgutil.walk_packages(package.__path__, f"{__package__}."):
        leaf = module.name.rsplit(".", 1)[-1]
        if leaf in _ENGINE_MODULES or "._shared" in module.name:
            continue
        importlib.import_module(module.name)
    return {**REGISTRY, **FILE_REGISTRY}


def entity_rules_for(filename: str) -> list[RuleSpec]:
    return [spec for spec in REGISTRY.values() if spec.filename == filename]
