#!/usr/bin/env python3
"""Report whether upstream moved since the position recorded in watch-state.json.

Usage:
    python tools/check_upstream.py
    python tools/check_upstream.py --json
    python tools/check_upstream.py --state /tmp/rewound.json --json
    python tools/check_upstream.py --advance spec

Two GitHub API reads, no clone, no Java, no model, so this is cheap enough to run
on a schedule and safe enough to run in CI. Exit codes are the interface:

    0   nothing moved
    1   the check itself failed: network, rate limit, malformed response
    10  the GTFS spec moved and the validator did not
    20  the validator moved, the only signal that may change our output

Exit 1 is not a detail. A watcher that reports "nothing moved" when it could not
reach the network converts an outage into a green light.

The asymmetry between 10 and 20 is the design. Parity is with the pinned jar, not
with the spec, so a merged spec change upstream has not implemented is a fact
about the future rather than work. See
the two-tier rule below.

Parity is with the pinned jar, not with the GTFS spec, so the two signals are not
interchangeable. A spec change MobilityData have merged but not released cannot
change our behaviour without creating a deliberate divergence, so exit 10 is
advisory and only exit 20 is actionable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

STATE = Path(__file__).resolve().parents[1] / "upstream/watch-state.json"
API = "https://api.github.com"
PAGE = 100
TIMEOUT = 30

EXIT_UNCHANGED = 0
EXIT_FAILED = 1
EXIT_SPEC_MOVED = 10
EXIT_VALIDATOR_MOVED = 20

# Upstream tags every release vMAJOR.MINOR.PATCH. Anything else, a release
# candidate or a moved-on branch tag, is reported to the reader and never chosen
# automatically: bumping the pin to a prerelease is a decision, not a default.
SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
PR_NUMBER = re.compile(r"#(\d+)\)?\s*$")


class CheckFailed(Exception):
    """The check could not be completed, which is distinct from upstream not moving."""


def fetch(url: str, token: str | None) -> list[dict]:
    """One GitHub API read returning a JSON array, or CheckFailed."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "gtfs-validator-upstream-watch",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310  # constant https API base
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        limited = error.headers.get("X-RateLimit-Remaining") == "0"
        reason = "rate limited; set GITHUB_TOKEN" if limited else f"HTTP {error.code}"
        raise CheckFailed(f"{url}: {reason}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise CheckFailed(f"cannot reach {url}: {error}") from error
    except json.JSONDecodeError as error:
        raise CheckFailed(f"{url} did not return JSON: {error}") from error
    if not isinstance(payload, list):
        raise CheckFailed(f"{url} returned {type(payload).__name__}, expected a list")
    return payload


def newest_release(tags: list[dict]) -> tuple[str, str]:
    """The highest vMAJOR.MINOR.PATCH tag and the commit behind it.

    Sorted by parsed version rather than by the order the API returns or by
    string order, both of which put v9.0.0 above v10.0.0.
    """
    releases = [
        (tuple(int(part) for part in match.groups()), tag["name"], tag["commit"]["sha"])
        for tag in tags
        if (match := SEMVER.match(tag.get("name", "")))
    ]
    if not releases:
        raise CheckFailed("no vMAJOR.MINOR.PATCH tag in the first page of tags")
    _, name, sha = max(releases)
    return name, sha


def unparsed_tags(tags: list[dict]) -> tuple[str, ...]:
    """Tags that are not plain releases, so a human sees a v9.0.0-rc1 we ignored."""
    return tuple(tag["name"] for tag in tags if not SEMVER.match(tag.get("name", "")))[:5]


def commits_since(commits: list[dict], last: str) -> tuple[tuple[dict, ...], bool]:
    """Commits newer than `last`, newest first, and whether the walk fell off the page.

    Falling off the page means the recorded sha is not in the returned window: we
    are more than a page behind, or the sha is wrong. Either way the spec moved,
    and saying so with a truncation marker beats failing the whole check.
    """
    fresh: list[dict] = []
    for commit in commits:
        if commit.get("sha") == last:
            return tuple(fresh), False
        subject = commit.get("commit", {}).get("message", "").split("\n")[0]
        pr = PR_NUMBER.search(subject)
        fresh.append(
            {
                "sha": commit.get("sha", ""),
                "subject": subject,
                "date": commit.get("commit", {}).get("committer", {}).get("date", ""),
                "pr": int(pr.group(1)) if pr else None,
            }
        )
    return tuple(fresh), True


@dataclass(frozen=True)
class Delta:
    """What moved. Built by `compare` from payloads, so it is testable without a network."""

    old_tag: str
    new_tag: str
    new_commit: str
    ignored_tags: tuple[str, ...]
    spec_commits: tuple[dict, ...]
    spec_truncated: bool

    @property
    def validator_moved(self) -> bool:
        return self.new_tag != self.old_tag

    @property
    def spec_moved(self) -> bool:
        return bool(self.spec_commits) or self.spec_truncated

    @property
    def exit_code(self) -> int:
        if self.validator_moved:
            return EXIT_VALIDATOR_MOVED
        return EXIT_SPEC_MOVED if self.spec_moved else EXIT_UNCHANGED


def compare(state: dict, tags: list[dict], commits: list[dict]) -> Delta:
    tag, sha = newest_release(tags)
    fresh, truncated = commits_since(commits, state["spec"]["commit"])
    return Delta(
        old_tag=state["validator"]["tag"],
        new_tag=tag,
        new_commit=sha,
        ignored_tags=unparsed_tags(tags),
        spec_commits=fresh,
        spec_truncated=truncated,
    )


def render(delta: Delta, state: dict) -> str:
    lines = []
    if delta.validator_moved:
        lines.append(
            f"validator moved: {delta.old_tag} -> {delta.new_tag} ({delta.new_commit[:8]})"
        )
        lines.append("  bump the pin, re-run the generators, and let the diff name the work")
    else:
        lines.append(f"validator unchanged at {delta.old_tag}")
    if delta.ignored_tags:
        lines.append(f"  tags not read as releases: {', '.join(delta.ignored_tags)}")

    path = state["spec"]["path"]
    if delta.spec_truncated:
        lines.append(
            f"spec moved: the recorded sha is not in the last {PAGE} commits to {path}, "
            "so either we are further behind than that or the recorded sha is wrong"
        )
    elif delta.spec_commits:
        lines.append(f"spec moved: {len(delta.spec_commits)} commit(s) to {path}")
        for commit in delta.spec_commits:
            lines.append(f"  {commit['date'][:10]}  {commit['sha'][:8]}  {commit['subject']}")
        lines.append("  advisory only: record it in upstream/pending-spec-changes.md")
    else:
        lines.append(f"spec unchanged at {state['spec']['commit'][:8]}")
    return "\n".join(lines)


def as_json(delta: Delta, state: dict) -> str:
    return json.dumps(
        {
            "validator": {
                "moved": delta.validator_moved,
                "from": {"tag": delta.old_tag, "commit": state["validator"]["commit"]},
                "to": {"tag": delta.new_tag, "commit": delta.new_commit},
                "ignored_tags": list(delta.ignored_tags),
            },
            "spec": {
                "moved": delta.spec_moved,
                "path": state["spec"]["path"],
                "from": state["spec"]["commit"],
                "commits": list(delta.spec_commits),
                "truncated": delta.spec_truncated,
            },
            "exit_code": delta.exit_code,
        },
        indent=2,
    )


def advance(state: dict, delta: Delta, what: str, path: Path) -> None:
    """Rewrite the recorded position to what was just observed.

    Only after the change it represents has been handled. Advancing first loses
    the signal, and nothing else in the repository remembers it.
    """
    if what in ("validator", "both"):
        state["validator"]["tag"] = delta.new_tag
        state["validator"]["commit"] = delta.new_commit
    if what in ("spec", "both") and delta.spec_commits:
        newest = delta.spec_commits[0]
        state["spec"]["commit"] = newest["sha"]
        state["spec"]["subject"] = newest["subject"]
    state["checked"] = datetime.now(UTC).date().isoformat()
    path.write_text(json.dumps(state, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--state", type=Path, default=STATE, help="path to watch-state.json")
    parser.add_argument("--json", action="store_true", help="machine-readable delta on stdout")
    parser.add_argument(
        "--advance",
        choices=("spec", "validator", "both"),
        help="record the observed position; only once the change has been handled",
    )
    args = parser.parse_args(argv)

    try:
        state = json.loads(args.state.read_text())
        token = os.environ.get("GITHUB_TOKEN")
        tags = fetch(f"{API}/repos/{state['validator']['repo']}/tags?per_page={PAGE}", token)
        query = urllib.parse.urlencode({"path": state["spec"]["path"], "per_page": PAGE})
        commits = fetch(f"{API}/repos/{state['spec']['repo']}/commits?{query}", token)
        delta = compare(state, tags, commits)
    except (CheckFailed, OSError, KeyError, json.JSONDecodeError) as error:
        print(f"check failed: {error}", file=sys.stderr)
        return EXIT_FAILED

    print(as_json(delta, state) if args.json else render(delta, state))
    if args.advance:
        advance(state, delta, args.advance, args.state)
    return delta.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
