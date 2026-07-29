"""One pass over a table feeding several per-row consumers.

The profiled cost of the file-rule stage on the largest feeds is the same table
streamed once per rule: ten full passes over a 997k-row feed, a dozen over
684-BE's 13M rows. The hub streams the table once for all of them while
preserving the sequential contract rule by rule: each consumer's notices come
out in its own emission order inside its own capped container, a consumer that
raises loses only its own notices and surfaces its exception for the runner's
`_report_failure`, and a failed table dependency silences every consumer the
same way it silenced each rule's own `rows()` read.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from gtfs_validator.context import Context
from gtfs_validator.notices import Notice, NoticeContainer
from gtfs_validator.rules.feedview import DependencyFailed


class ScanConsumer(Protocol):
    def row(self, row: dict) -> Iterable[Notice] | None:
        """Per-row work; notices returned here land in the buffer immediately.

        Streaming them per row rather than holding them for `finish` is what
        keeps the hub's memory bounded: the buffer applies the destination's
        caps as each notice arrives, exactly as the sequential runner's
        buffered container does while a rule's generator runs.
        """

    def finish(self) -> Iterable[Notice]: ...


Factory = Callable[[object, Context], "ScanConsumer | None"]


def run_scan(
    feed,
    ctx: Context,
    table: str,
    consumers: list[tuple[str, Factory]],
    caps: tuple[int, int, int] | None = None,
) -> list[tuple[str, NoticeContainer | Exception]]:
    """The per-code results, in the order given, which is registry order.

    A factory returning None is inapplicable (its own header or dependency
    precondition failed) and is omitted from the results entirely, matching a
    rule that returned without yielding. `caps` mirrors the destination
    container's `(max_total, max_per_type, max_exports_per_type)` so the buffer
    applies the same caps on the way in that the runner's buffered containers
    do; None keeps the defaults.
    """
    live: list[tuple[str, ScanConsumer, NoticeContainer]] = []
    failed: list[tuple[str, Exception]] = []
    for code, factory in consumers:
        try:
            consumer = factory(feed, ctx)
        except DependencyFailed:  # silent-ok - the skip *is* the behaviour
            continue
        except Exception as exc:  # noqa: BLE001 - isolated per consumer, reported
            failed.append((code, exc))
            continue
        if consumer is not None:
            produced = NoticeContainer(*caps) if caps else NoticeContainer()
            live.append((code, consumer, produced))
    if live:
        _pump(feed, table, live, failed)
    results: list[tuple[str, NoticeContainer | Exception]] = []
    for code, consumer, produced in live:
        try:
            produced.add_all(consumer.finish())
        except DependencyFailed:  # silent-ok - a finish() reading a failed table skips
            continue
        except Exception as exc:  # noqa: BLE001 - isolated per consumer
            results.append((code, exc))
            continue
        results.append((code, produced))
    results.extend(failed)
    order = {code: position for position, (code, _) in enumerate(consumers)}
    results.sort(key=lambda item: order[item[0]])
    return results


def _pump(
    feed,
    table: str,
    live: list[tuple[str, ScanConsumer, NoticeContainer]],
    failed: list[tuple[str, Exception]],
) -> None:
    """Feed every live consumer from one read of the table, mutating in place.

    The cursor advances under its own guard: sequentially each rule's pass would
    hit the same read error and draw its own runtime_exception_in_validator_error
    while later rules still ran, so a mid-read failure costs every live consumer
    its buffer and surfaces one exception per consumer, never the whole stage. A
    DependencyFailed from the read silences everyone with nothing reported, and
    factory failures already in `failed` happened before any read, so, exactly
    as each rule's own pass would have, they still report.
    """
    try:
        rows = iter(feed.rows(table))
    except DependencyFailed:  # silent-ok - the skip *is* the behaviour
        live.clear()
        return
    while True:
        try:
            row = next(rows)
        except StopIteration:
            return
        except DependencyFailed:  # silent-ok - the skip *is* the behaviour
            live.clear()
            return
        except Exception as exc:  # noqa: BLE001 - isolated per consumer, reported
            failed.extend((code, exc) for code, _, _ in live)
            live.clear()
            return
        # Reverse index walk so a raising consumer can be dropped mid-pass
        # without disturbing the neighbours' turn.
        for index in range(len(live) - 1, -1, -1):
            code, consumer, produced = live[index]
            try:
                emitted = consumer.row(row)
                if emitted is not None:
                    produced.add_all(emitted)
            except DependencyFailed:  # silent-ok - the skip *is* the behaviour
                live.pop(index)
            except Exception as exc:  # noqa: BLE001 - isolated per consumer
                failed.append((code, exc))
                live.pop(index)
