"""`--url`: fetch a feed before validating it.

Upstream's `createGtfsInput` branches on `--storage_directory`. With one, it
downloads to `<dir>/gtfs.zip` and keeps it. Without one, it downloads *into
memory* and validates from there.

**We always download to a file**, and delete it afterwards when no storage
directory was given. The visible behaviour is the same, and the reason to
diverge is the one this project keeps running into: a real feed reaches
hundreds of megabytes, and the whole engine is built to stream a
multi-million-row stop_times.txt off disk rather than hold it. Reading the
archive into a bytes object to honour "in memory" literally would put the peak
back exactly where the design spent plans removing it. Recorded in
a deliberate difference with no observable effect on either report.

The User-Agent names gtfs-validator rather than the jar, for the same reason
`summary.validatorVersion` does: a server's logs should say which client
actually called.
"""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

GTFS_ZIP_FILENAME = "gtfs.zip"

# Matches upstream's shape, `<name>/<version> (<runtime>)`, without its name.
USER_AGENT_PREFIX = "gtfs-validator"


def user_agent(version: str, python_version: str) -> str:
    return f"{USER_AGENT_PREFIX}/{version} (Python {python_version})"


def download(url: str, target: Path, agent: str, timeout: int = 300) -> Path:
    """Fetch `url` to `target`, creating the parent directory as upstream does.

    Streamed through `shutil.copyfileobj` rather than `read()` so a large feed
    never lands in memory in one piece.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": agent})  # noqa: S310
    with (
        urllib.request.urlopen(request, timeout=timeout) as response,  # noqa: S310
        target.open("wb") as handle,
    ):
        shutil.copyfileobj(response, handle)
    return target


def target_for(storage_directory: str | None, work: Path) -> Path:
    """`<storage_directory>/gtfs.zip`, or a path inside the run's temp dir."""
    base = Path(storage_directory) if storage_directory else work
    return base / GTFS_ZIP_FILENAME
