"""How far a table got through loading, which decides whether it is indexed.

Upstream's CsvFileLoader returns a container carrying one of these, and only
PARSABLE_HEADERS_AND_ROWS reaches createContainerForHeaderAndEntities, the call
that builds the key indices. Every other status returns a container with no
entities at all, so duplicate_key and more_than_one_entity cannot fire for it.

That has two consequences worth spelling out, because both are surprising:

  * A single bad row suppresses duplicate_key for the *whole* file. A stops.txt
    with two rows sharing a stop_id and one unrelated row carrying an
    invalid_float reports only the invalid_float.
  * Header errors stop the file before any row is read, so no row-level notice
    can fire either. TableStatus's own javadoc says "the other rows were not
    scanned".

Single-entity validators are unaffected: they run inside the row loop, on each
clean row, before the status is known.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TableStatus(Enum):
    EMPTY_FILE = "EMPTY_FILE"
    MISSING_FILE = "MISSING_FILE"
    PARSABLE_HEADERS_AND_ROWS = "PARSABLE_HEADERS_AND_ROWS"
    INVALID_HEADERS = "INVALID_HEADERS"
    UNPARSABLE_ROWS = "UNPARSABLE_ROWS"


@dataclass
class TableLoad:
    """The status of one table, filled in as its stages run.

    Mutable and passed down rather than returned, because the parse and typing
    stages are generators: the caller has the object before the rows are drawn
    through it, and the final status is only known once they have been.
    """

    status: TableStatus = TableStatus.PARSABLE_HEADERS_AND_ROWS
    # The columns the file actually declared. Stage 5 needs it for the rules
    # that upstream gates on shouldCallValidate, which is a header test rather
    # than a value test, and re-reading the zip entry to recover it would undo
    # the streaming the loader is built around.
    columns: frozenset[str] = frozenset()

    def fail(self, status: TableStatus) -> None:
        """Record a terminal status, keeping the first one seen.

        Header validation runs before any row, so an INVALID_HEADERS table never
        reaches the row loop and cannot be downgraded to UNPARSABLE_ROWS.
        """
        if self.status is TableStatus.PARSABLE_HEADERS_AND_ROWS:
            self.status = status

    @property
    def is_indexable(self) -> bool:
        return self.status is TableStatus.PARSABLE_HEADERS_AND_ROWS
