"""Central error ID registry. See guides/error-id-registry.md.

Rules:
  1. Never reuse a retired ID - mark it `# retired` and leave it in place.
  2. One ID per distinct cause, not per raise site.
  3. Numbers are stable; append, never renumber.
  4. Domain prefix (3-5 letters) is required.

Raise via AppError(ErrorIds.X, "...", {...}). Log lines include the ID so
grep, telemetry, and agents can all find every occurrence with one search.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any


class ErrorIds(StrEnum):
    # ── GTFS container / feed input (FEED) ──────────────────────────────
    # These are runtime failures that land in system_errors.json. A malformed
    # feed is NOT a runtime failure: it produces notices. Use these only when
    # the tool itself cannot proceed.
    FEED_UNREADABLE_ARCHIVE = "E_FEED_001"
    FEED_DECODE_FAIL = "E_FEED_002"
    FEED_TABLE_READ_FAIL = "E_FEED_003"

    # ── Upstream sync (SYNC) ──────────────────────────────────────
    SYNC_CLONE_FAIL = "E_SYNC_001"
    SYNC_PARSE_FAIL = "E_SYNC_002"
    SYNC_COUNT_MISMATCH = "E_SYNC_003"

    # ── Feed store (STORE) ───────────────────────────────────────────────────
    # SQLite cannot parameterise a table or column name, so the store builds
    # those into SQL text. This fires if a name that did not come from the
    # generated schema registry ever reaches that path.
    STORE_UNSAFE_IDENTIFIER = "E_STORE_001"

    # ── Field typing (TYPE) ──────────────────────────────────────────────────
    # A decimal whose plain-string rendering cannot fit in a Java String. The jar
    # dies with OutOfMemoryError here and reports a thread_execution_error, so
    # there is no upstream fieldValue to match; refusing beats writing gigabytes.
    TYPE_DECIMAL_UNRENDERABLE = "E_TYPE_001"

    # ── Config (CFG) ─────────────────────────────────────────────────────────
    CFG_MISSING = "E_CFG_001"
    CFG_INVALID_JSON = "E_CFG_002"
    CFG_SCHEMA_FAIL = "E_CFG_003"
    CFG_ENV_MISSING = "E_CFG_004"

    # ── Filesystem (FS) ──────────────────────────────────────────────────────
    FS_NOT_FOUND = "E_FS_001"
    FS_PERMISSION = "E_FS_002"
    FS_DISK_FULL = "E_FS_003"
    FS_READ_FAIL = "E_FS_004"
    FS_WRITE_FAIL = "E_FS_005"

    # ── Network (NET) ────────────────────────────────────────────────────────
    NET_TIMEOUT = "E_NET_001"
    NET_DNS = "E_NET_002"
    NET_TLS = "E_NET_003"
    NET_RATE_LIMITED = "E_NET_004"
    NET_UNAVAILABLE = "E_NET_005"
    NET_BAD_SHAPE = "E_NET_006"

    # ── Tool execution (TOOL) ────────────────────────────────────────────────
    TOOL_ABORTED = "E_TOOL_001"
    TOOL_BAD_INPUT = "E_TOOL_002"
    TOOL_TIMEOUT = "E_TOOL_003"
    TOOL_PERMISSION_DENIED = "E_TOOL_004"
    TOOL_SECURITY_BLOCKED = "E_TOOL_005"

    # ── LLM / API (LLM) ──────────────────────────────────────────────────────
    LLM_RATE_LIMITED = "E_LLM_001"
    LLM_CONTEXT_OVERFLOW = "E_LLM_002"
    LLM_BAD_RESPONSE = "E_LLM_003"

    # Add new domains/IDs below. Keep the comment block above each domain.


class AppError(Exception):
    """Base error: every raise carries a stable ID plus structured context."""

    def __init__(
        self,
        error_id: ErrorIds,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.id = error_id
        self.context = context or {}

    def to_log_line(self) -> str:
        ctx = " ".join(f"{k}={json.dumps(v, default=str)}" for k, v in self.context.items())
        return f"[{self.id}] {self}{' ' + ctx if ctx else ''}"


class CarriedFailure(Exception):
    """A worker-process failure, pre-rendered so it survives pickling.

    Exceptions travel from pool workers to the parent by pickle, and not every
    exception reconstructs: `AppError.__init__` takes arguments its `args` tuple
    does not match, which crashed the pool's result handler and left the run
    hanging. The worker therefore renders the two fields the system-error notices
    need, exactly as the parent-side renderer would have, and sends those.
    """

    def __init__(self, class_name: str, message: str) -> None:
        super().__init__(class_name, message)
        self.class_name = class_name
        self.message = message


def carry(exc: Exception) -> CarriedFailure:
    """The picklable stand-in for `exc`, rendered the way the renderers render."""
    if isinstance(exc, CarriedFailure):
        return exc
    message = exc.to_log_line() if isinstance(exc, AppError) else str(exc)
    return CarriedFailure(type(exc).__name__, message)
