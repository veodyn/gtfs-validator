"""The op-stream a parallel load worker records, and its replay.

The sequential loader interleaves capped `add` calls with `merge` calls that
deliberately bypass the caps (csvparse's header notices), and a review measured
the difference at exactly one notice past the per-type cap. Replaying the ops,
rather than the retained notices, reproduces both behaviours in the main
process; the caps are global running state, so they are recomputed only there.

Worker memory is bounded twice over: the recording container retains no
notices of its own (the base bookkeeping stays exact with `max_total` zero),
and an `add` the worker can already prove unretainable (its local count passed
the per-type cap, and local counts never exceed the parent's at replay time)
aggregates into one mutable ``["counts", key, severity, n]`` op per key rather
than one op per notice. The count bookkeeping is commutative, so the
aggregate's position in the stream cannot change the report.
"""

from __future__ import annotations

import sys

from gtfs_validator.notices import NoticeContainer

_UNCAPPED = sys.maxsize


class _RecordingContainer(NoticeContainer):
    """A worker-side container that records the loader's op stream for replay."""

    def __init__(self, destination_caps: tuple[int, int]) -> None:
        super().__init__(0, _UNCAPPED, _UNCAPPED)
        self.ops: list[tuple | list] = []
        self._cap_total, self._cap_per_type = destination_caps
        self._sim_total = 0
        self._sim_counts: dict[str, int] = {}
        self._count_refs: dict[str, list] = {}

    def add(self, notice) -> None:
        super().add(notice)
        key = notice.mapping_key
        count = self._sim_counts.get(key, 0) + 1
        self._sim_counts[key] = count
        if self._sim_total >= self._cap_total or count > self._cap_per_type:
            # Mutable on purpose: the split loader's tagged wrapper copies the
            # reference, so increments reach both lists.
            ref = self._count_refs.get(key)
            if ref is not None:
                ref[3] += 1
            else:
                ref = ["counts", key, notice.severity, 1]
                self._count_refs[key] = ref
                self.ops.append(ref)
        else:
            self._sim_total += 1
            self.ops.append(("add", notice))

    def merge(self, other) -> None:
        super().merge(other)
        self.ops.append(
            (
                "merge",
                (
                    tuple(other._notices),
                    dict(other._counts),
                    other._has_errors,
                    other._has_warnings,
                    other._error_count,
                ),
            )
        )


def _replay(notices: NoticeContainer, ops: list[tuple | list]) -> None:
    """Apply one table's recorded ops to the real container, in order."""
    for op in ops:
        kind = op[0]
        if kind == "add":
            notices.add(op[1])
        elif kind == "counts":
            notices.observe_dropped(op[1], op[2], op[3])
        else:
            retained, counts, has_errors, has_warnings, error_count = op[1]
            source = NoticeContainer(_UNCAPPED, _UNCAPPED, _UNCAPPED)
            source._notices = list(retained)
            source._counts = counts
            source._has_errors = has_errors
            source._has_warnings = has_warnings
            source._error_count = error_count
            notices.merge(source)
