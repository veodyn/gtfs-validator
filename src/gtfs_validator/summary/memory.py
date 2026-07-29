"""`summary.memoryUsageRecords`, which carries Python numbers under Java's names.

The field names come from `Runtime`: `totalMemory` is the heap the JVM has
allocated, `freeMemory` the unused part of it, `maxMemory` the `-Xmx` ceiling.
None of the three has an exact CPython equivalent, and the decision recorded in
the CLI parity spec was to report real measurements rather than `null`. So the
mapping is stated here, at the only place the numbers are produced, because a
reader who assumes JVM semantics will misread them:

| Field | Jar | Here |
|---|---|---|
| `totalMemory` | heap allocated | peak RSS of this process, in bytes |
| `freeMemory` | allocated but unused | `maxMemory - totalMemory`, or null when unbounded |
| `maxMemory` | `-Xmx` | `RLIMIT_AS`, or null when unlimited |
| `diffMemory` | delta since the previous record | the same delta |

`totalMemory` is a **peak**, not a current reading. `resource.getrusage` is the
only process-memory source in the standard library, and it reports high-water
RSS; anything current would need /proc, which is Linux-only, or a third-party
package, which the runtime forbids. The consequence is that the numbers rise
monotonically and `diffMemory` is never negative, where the jar's often is.
"""

from __future__ import annotations

import resource
import sys
from dataclasses import dataclass

# ru_maxrss is bytes on macOS and the BSDs, kilobytes on Linux. Getting this
# wrong scales every number by 1024 and nothing would fail loudly.
_RSS_TO_BYTES = 1 if sys.platform == "darwin" else 1024


def _peak_rss() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * _RSS_TO_BYTES


def _address_space_limit() -> int | None:
    soft, _ = resource.getrlimit(resource.RLIMIT_AS)
    return None if soft == resource.RLIM_INFINITY else soft


@dataclass
class Register:
    """`MemoryUsageRegister`: records in the order they were taken."""

    records: list[dict[str, object]]

    @classmethod
    def new(cls) -> Register:
        return cls(records=[])

    def register(self, key: str) -> None:
        """Take a reading and name it after the stage that just finished."""
        total = _peak_rss()
        ceiling = _address_space_limit()
        previous = self.records[-1]["totalMemory"] if self.records else None
        self.records.append(
            {
                "key": key,
                "totalMemory": total,
                "freeMemory": None if ceiling is None else ceiling - total,
                "maxMemory": ceiling,
                "diffMemory": None if previous is None else total - int(previous),
            }
        )

    def as_list(self) -> list[dict[str, object]]:
        return list(self.records)
