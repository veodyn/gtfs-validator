"""The upstream watcher's comparison, which decides whether anything moved.

Fetching is separated from comparing in the script precisely so these run without
a network. The exit code is the contract the workflow and the skill both read, so
it is asserted directly rather than inferred from the printed text.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import check_upstream
from check_upstream import (
    EXIT_FAILED,
    EXIT_SPEC_MOVED,
    EXIT_UNCHANGED,
    EXIT_VALIDATOR_MOVED,
    CheckFailed,
    advance,
    commits_since,
    compare,
    main,
    newest_release,
    unparsed_tags,
)

PINNED = "d74d7177f9f7c6bc7adc69508bb939362f2cf770"
SPEC_SHA = "ac663b574aae7223e45044b7733a1f101f0ab907"


def tag(name: str, sha: str = "0" * 40) -> dict:
    return {"name": name, "commit": {"sha": sha}}


def commit(sha: str, subject: str, date: str = "2026-04-30T15:08:27Z") -> dict:
    return {
        "sha": sha,
        "commit": {"message": f"{subject}\n\nbody text", "committer": {"date": date}},
    }


def state(tag_name: str = "v8.0.1", spec_sha: str = SPEC_SHA) -> dict:
    return {
        "validator": {"repo": "MobilityData/gtfs-validator", "tag": tag_name, "commit": PINNED},
        "spec": {
            "repo": "google/transit",
            "path": "gtfs/spec/en/reference.md",
            "commit": spec_sha,
            "subject": "Update revision history - April 2026 (#627)",
        },
        "checked": "2026-07-29",
    }


TAGS = [tag("v8.0.1", PINNED), tag("v8.0.0"), tag("v2.0.0-docs")]
COMMITS = [commit(SPEC_SHA, "Update revision history - April 2026 (#627)")]


def test_nothing_moved_exits_zero():
    delta = compare(state(), TAGS, COMMITS)
    assert delta.exit_code == EXIT_UNCHANGED
    assert not delta.validator_moved
    assert not delta.spec_moved


def test_spec_alone_moving_is_advisory():
    fresh = [commit("aaa", "Add safe duration fields to trips.txt (#598)"), *COMMITS]
    delta = compare(state(), TAGS, fresh)
    assert delta.exit_code == EXIT_SPEC_MOVED
    assert not delta.validator_moved
    assert [c["pr"] for c in delta.spec_commits] == [598]


def test_validator_moving_outranks_the_spec():
    """20 is the actionable code, so a week where both moved still reports 20."""
    fresh = [commit("aaa", "Add safe duration fields to trips.txt (#598)"), *COMMITS]
    delta = compare(state(tag_name="v8.0.0"), TAGS, fresh)
    assert delta.exit_code == EXIT_VALIDATOR_MOVED
    assert delta.validator_moved and delta.spec_moved
    assert (delta.new_tag, delta.new_commit) == ("v8.0.1", PINNED)


def test_a_missing_recorded_sha_reports_movement_rather_than_failing():
    """More than a page behind, or a wrong sha. Both mean the spec moved."""
    delta = compare(state(spec_sha="nosuchsha"), TAGS, COMMITS)
    assert delta.spec_truncated
    assert delta.exit_code == EXIT_SPEC_MOVED


def test_releases_sort_by_version_not_by_string():
    """v9.0.0 sorts above v10.0.0 as text, which is how a watcher silently stops working."""
    assert newest_release([tag("v9.0.0"), tag("v10.0.0", "abc")]) == ("v10.0.0", "abc")


def test_a_prerelease_is_reported_and_never_chosen():
    tags = [tag("v8.0.1", PINNED), tag("v9.0.0-rc1")]
    assert newest_release(tags) == ("v8.0.1", PINNED)
    assert unparsed_tags(tags) == ("v9.0.0-rc1",)


def test_no_readable_release_is_a_failure_not_a_quiet_zero():
    with pytest.raises(CheckFailed):
        newest_release([tag("nightly"), tag("v2.0.0-docs")])


def test_only_the_subject_line_of_a_commit_is_read():
    fresh, truncated = commits_since([commit("aaa", "Add stops.stop_access field (#515)")], "zzz")
    assert truncated
    assert fresh[0]["subject"] == "Add stops.stop_access field (#515)"
    assert fresh[0]["pr"] == 515


def test_a_commit_without_a_pr_number_still_reports():
    fresh, _ = commits_since([commit("aaa", "Fix a typo")], "zzz")
    assert fresh[0]["pr"] is None


def test_advance_records_only_what_it_is_told_to(tmp_path: Path):
    """Advancing the validator on a spec-only week would lose the pin's real position."""
    path = tmp_path / "watch-state.json"
    current = state(tag_name="v8.0.0")
    fresh = [commit("aaa", "Add safe duration fields (#598)"), *COMMITS]
    delta = compare(current, TAGS, fresh)

    advance(current, delta, "spec", path)
    written = json.loads(path.read_text())
    assert written["spec"]["commit"] == "aaa"
    assert written["validator"]["tag"] == "v8.0.0"

    advance(current, delta, "validator", path)
    written = json.loads(path.read_text())
    assert written["validator"] == {
        "repo": "MobilityData/gtfs-validator",
        "tag": "v8.0.1",
        "commit": PINNED,
    }


def test_advance_leaves_the_spec_alone_when_nothing_moved(tmp_path: Path):
    path = tmp_path / "watch-state.json"
    current = state()
    advance(current, compare(current, TAGS, COMMITS), "both", path)
    assert json.loads(path.read_text())["spec"]["commit"] == SPEC_SHA


def _write_state(tmp_path: Path) -> Path:
    path = tmp_path / "watch-state.json"
    path.write_text(json.dumps(state()))
    return path


def test_main_returns_the_delta_exit_code(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(
        check_upstream, "fetch", lambda url, token: TAGS if "tags" in url else COMMITS
    )
    assert main(["--state", str(_write_state(tmp_path)), "--json"]) == EXIT_UNCHANGED
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == EXIT_UNCHANGED
    assert payload["validator"]["ignored_tags"] == ["v2.0.0-docs"]


def test_an_unreachable_api_never_reports_nothing_moved(tmp_path: Path, monkeypatch, capsys):
    """The failure this design exists to avoid: an outage rendered as a green light."""

    def unreachable(url, token):
        raise CheckFailed("cannot reach github")

    monkeypatch.setattr(check_upstream, "fetch", unreachable)
    assert main(["--state", str(_write_state(tmp_path))]) == EXIT_FAILED
    assert "check failed" in capsys.readouterr().err


def test_a_malformed_state_file_fails_rather_than_passing(tmp_path: Path, capsys):
    path = tmp_path / "watch-state.json"
    path.write_text('{"validator": {"tag": "v8.0.1"}}')
    assert main(["--state", str(path)]) == EXIT_FAILED
    assert "check failed" in capsys.readouterr().err
