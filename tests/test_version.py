"""The version string lives in four files, and nothing else makes them agree.

`gtfs_validator.version.VERSION` is what a report carries, and `pyproject.toml` is
what PyPI carries. A release where those two disagree ships an archive whose
`summary.validatorVersion` names a version that was never published, which is
undetectable from the report alone.

The alias package is here for the same reason: its dependency floor names a
gtfs-validator release, and a floor above what exists is uninstallable.

`version.py`'s docstring claimed this file existed before it did.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from gtfs_validator import __version__
from gtfs_validator.version import VERSION

ROOT = Path(__file__).resolve().parents[1]
ALIAS = ROOT / "packaging/gtfs-lint-alias/pyproject.toml"


def _project(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)["project"]


def test_the_reported_version_matches_the_one_pypi_would_carry() -> None:
    assert _project(ROOT / "pyproject.toml")["version"] == VERSION


def test_the_package_attribute_is_the_same_object_not_a_second_copy() -> None:
    assert __version__ is VERSION


def test_the_alias_declares_the_same_version() -> None:
    assert _project(ALIAS)["version"] == VERSION


def test_the_alias_floor_is_a_release_that_exists() -> None:
    """A floor above the current version could never resolve.

    Written as a comparison against VERSION rather than a literal so bumping the
    version does not silently leave the floor behind.
    """
    (dependency,) = _project(ALIAS)["dependencies"]
    name, _, floor = dependency.partition(">=")
    assert name == "gtfs-validator", f"expected a floor on gtfs-validator, got {dependency!r}"
    assert floor == VERSION


def test_the_shipped_version_is_not_a_pre_release() -> None:
    """pip skips pre-releases unless asked, so a `.dev` or `rc` on the index makes
    the README's plain `pip install gtfs-validator` fail to resolve at all.

    Matched positively against the final-release form rather than by looking for
    `dev`/`a`/`b`/`rc` markers: the marker list is a guess at what a pre-release
    looks like, and `\\d+(\\.\\d+)*` is what one is not.
    """
    assert re.fullmatch(r"\d+(\.\d+)*", VERSION), (
        f"{VERSION} is a pre-release; either ship a final version or change the "
        f"README's install line to pass --pre"
    )
