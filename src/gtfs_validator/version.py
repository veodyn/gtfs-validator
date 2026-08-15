"""The version gtfs-validator reports for itself.

`summary.validatorVersion` carries this rather than the pinned upstream tag. The
field names the validator that ran, and emitting `8.0.1` would make an archived
report indistinguishable from one the jar produced, which is a provenance claim
we are not entitled to make. A consumer pinning on `8.0.1` sees a surprise, and
that is the correct surprise. Decision recorded in the CLI parity design.

The rule-set generation is a separate fact and lives in
`data/canonical_notices.json` under `_meta.tag`.

Kept in a module of its own so `pyproject.toml` and the report cannot drift:
`tests/test_version.py` asserts they agree, and covers the alias package's
dependency floor too. That sentence was here before the test was, which is the
argument for the test: three copies of the string were guarded by a claim.
"""

from __future__ import annotations

VERSION = "0.1.2"
