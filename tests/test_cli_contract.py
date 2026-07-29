"""Upstream's argument contract and exit codes, which a wrapper script sees.

Split from test_cli.py on the file-size limit. These are the cases where the
answer is a status code rather than a report, and every expected number here
was measured against the pinned jar rather than read off its source.
"""

import json

from gtfs_validator.cli import main


def test_url_is_fetched_and_a_failed_fetch_is_a_system_error(tmp_path, monkeypatch):
    """`-u` downloads. A fetch that fails is a runtime failure, not a usage error.

    It used to exit 2 with "not supported". Upstream downloads the feed, and a
    URL it cannot reach reaches `system_errors.json` and exits 255, the same as
    an unopenable file: measured on the jar, which returns Status.SYSTEM_ERRORS
    from the branch where it could not build a GtfsInput.
    """
    from gtfs_validator import fetch

    def refuse(url, target, agent, timeout=300):
        raise OSError("nope")

    monkeypatch.setattr(fetch, "download", refuse)
    out = tmp_path / "out"
    assert main(["-u", "https://example.com/feed.zip", "-o", str(out)]) == 255
    errors = json.loads((out / "system_errors.json").read_text())
    assert errors["notices"], "a failed fetch has to be recorded, not swallowed"


def test_url_and_input_together_are_a_usage_error(tmp_path, capsys):
    """Upstream refuses both at once, and says so before complaining about output."""
    assert main(["-i", "feed.zip", "-u", "https://example.com/f.zip", "-o", str(tmp_path)]) == 1
    assert "cannot be provided at the same time" in capsys.readouterr().err


def test_output_base_is_required_like_upstream(tmp_path, capsys):
    """No default for -o: the jar refuses a run that names neither -o nor --stdout."""
    assert main(["-i", str(tmp_path / "feed.zip")]) == 1
    assert "Must provide either --output_base or --stdout" in capsys.readouterr().err
