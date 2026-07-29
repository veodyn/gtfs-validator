"""Notice primitives.

Mirrors upstream's notice model closely enough that reports are comparable:
severity ordinals and the code+ordinal grouping key are both load-bearing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum


class Severity(IntEnum):
    """Matches upstream SeverityLevel declaration order; the ordinal is exported."""

    INFO = 0
    WARNING = 1
    ERROR = 2


@dataclass(frozen=True, slots=True)
class Notice:
    code: str
    severity: Severity
    context: dict[str, object] = field(default_factory=dict)

    @property
    def mapping_key(self) -> str:
        """Upstream groups and sorts notices by code concatenated with the ordinal."""
        return f"{self.code}{self.severity.value}"


MAX_TOTAL_NOTICES = 10_000_000
MAX_NOTICES_PER_TYPE = 100_000
MAX_EXPORTS_PER_TYPE = 1_000


class NoticeContainer:
    """Collects notices under the same caps upstream applies.

    The per-type count is incremented for every notice, including ones that are
    not retained, because the exported ``totalNotices`` is the true count.
    """

    def __init__(
        self,
        max_total: int = MAX_TOTAL_NOTICES,
        max_per_type: int = MAX_NOTICES_PER_TYPE,
        max_exports_per_type: int = MAX_EXPORTS_PER_TYPE,
    ) -> None:
        self.max_total = max_total
        self.max_per_type = max_per_type
        self.max_exports_per_type = max_exports_per_type
        self._notices: list[Notice] = []
        self._counts: dict[str, int] = {}
        self._has_errors = False
        self._has_warnings = False
        self._error_count = 0

    def add(self, notice: Notice) -> None:
        key = notice.mapping_key
        if notice.severity is Severity.ERROR:
            self._has_errors = True
            self._error_count += 1
        elif notice.severity is Severity.WARNING:
            self._has_warnings = True

        count = self._counts.get(key, 0) + 1
        self._counts[key] = count

        if len(self._notices) >= self.max_total or count > self.max_per_type:
            return
        self._notices.append(notice)

    def observe_dropped(self, mapping_key: str, severity: Severity, count: int = 1) -> None:
        """`add`'s bookkeeping without retention, for the parallel loader's replay.

        A worker that already knows a notice cannot be retained (its local count
        passed the per-type cap, and local counts never exceed the parent's at
        replay time) sends only the key, severity and how many; the counts, flags
        and `error_count` must still move exactly as that many capped `add` calls
        would move them.
        """
        if severity is Severity.ERROR:
            self._has_errors = True
            self._error_count += count
        elif severity is Severity.WARNING:
            self._has_warnings = True
        self._counts[mapping_key] = self._counts.get(mapping_key, 0) + count

    def add_all(self, notices: Iterable[Notice]) -> None:
        for notice in notices:
            self.add(notice)

    def merge(self, other: NoticeContainer) -> None:
        """Absorb another container, mirroring upstream NoticeContainer.addAll.

        Not the same as add_all over its notices: the counts are summed rather
        than recomputed, so a type that hit the per-type cap in the other
        container still contributes its full total. Forwarding only the retained
        notices would make totalNotices undercount.

        The caps are deliberately not re-applied to the merged notices, matching
        upstream: its javadoc warns that the result may hold more than the maxima,
        because each container already applied them on the way in.
        """
        self._notices.extend(other._notices)
        for key, count in other._counts.items():
            self._counts[key] = self._counts.get(key, 0) + count
        self._has_errors = self._has_errors or other._has_errors
        self._has_warnings = self._has_warnings or other._has_warnings
        self._error_count += other._error_count

    def count_for(self, mapping_key: str) -> int:
        return self._counts.get(mapping_key, 0)

    def in_order(self) -> tuple[Notice, ...]:
        """The retained notices in insertion order.

        For the parallel loader's merge: a worker collects a table's notices in an
        uncapped container, and the main process replays them through `add` in the
        canonical file-visit order, so the real container's caps and counts end up
        exactly as one sequential stream would have left them.
        """
        return tuple(self._notices)

    def grouped(self) -> dict[str, list[Notice]]:
        """Mapping key to retained notices, keys sorted as upstream's tree map sorts."""
        groups: dict[str, list[Notice]] = {}
        for notice in self._notices:
            groups.setdefault(notice.mapping_key, []).append(notice)
        return {key: groups[key] for key in sorted(groups)}

    def has_errors(self) -> bool:
        return self._has_errors

    def error_count(self) -> int:
        """Total ERROR-level notices added, including ones not retained.

        type_row reads it before and after a row to tell whether that row
        produced an ERROR, which decides whether the row is stored and
        entity-validated, matching CsvFileLoader.
        """
        return self._error_count

    def has_warnings(self) -> bool:
        return self._has_warnings
