# AGENTS.md

Instructions for coding agents working in this repository. Humans may find the
reasoning useful too, but the README is the better starting point.

## What this project is

A pure-Python reimplementation of MobilityData's Java GTFS validator, pinned to
its **v8.0.1** release (`d74d7177f9f7c6bc7adc69508bb939362f2cf770`). The whole
value is matching a rule set someone else owns, byte for byte where possible.

Throughout this repo, "upstream" and "the jar" mean MobilityData's validator.
"This project" means the Python one. The two share a name, so never write
`gtfs-validator` bare where a sentence has to say which.

## Hard constraints

Not negotiable without a deliberate decision to change them.

- **Stdlib only at runtime.** `sqlite3`, `csv`, `zipfile`, `json`, `zoneinfo`,
  `urllib`. A runtime import of anything third-party is a design change. Test
  and dev dependencies are unconstrained.
- **Python 3.11+.** The suite runs on 3.11, 3.13 and 3.14.
- **No pandas.** Row-level notices need exact source row numbers and bounded
  memory. DataFrames obstruct both.
- **One rule module per notice code**, named exactly after the code, registered
  by decorator. Shared logic goes in `src/gtfs_validator/rules/_shared/`, never
  copy-pasted.
- **Generated files are not hand-edited.** `src/gtfs_validator/data/*.json` and
  the table schemas come from upstream at the pin, via scripts in `tools/`. Fix
  the generator, re-run it, commit both. Hand-editing makes the drift tests lie.

## When upstream and intuition disagree, upstream wins

If a check looks wrong, the default assumption is that it faithfully mirrors
upstream. Read the Java before "fixing" it. Real upstream bugs get recorded as a
deliberate difference with the measurement that established them, in the comment
nearest the code that implements them, and summarised under "Deliberate
differences" in the README. Anything not recorded there is a defect.

**Corollary: never weaken a differential comparison to make it pass.** A red diff
against the jar is the deliverable, not an obstacle. This includes widening the
normaliser in `gtfs_validator.summary`, which enumerates the only fields any
byte comparison is allowed to ignore.

## Notices are data, not exceptions

A validation finding is a `Notice` appended to a `NoticeContainer`. Raising for a
malformed feed is wrong: feeds are expected to be malformed, that is the entire
product. Exceptions are for genuine runtime failures, and they belong in
`system_errors.json` with an id from `src/gtfs_validator/error_ids.py`.

## Verifying a change

Six checks, and they cover different things. Run the ones your change can reach.

```bash
python -m pytest                                    # behaviour, per unit
ruff check src/ tests/ tools/                       # style and the lint rules
DATE=2026-06-01 PYTHON=.venv/bin/python \
  tools/diff_against_upstream.sh feed.zip jar.jar   # notices, per feed
DATE=2026-06-01 PYTHON=.venv/bin/python \
  tools/diff_full_output_against_upstream.sh feed.zip jar.jar   # summary + HTML
PYTHONPATH=src python tools/measure_scale.py        # time and memory, one big feed
PYTHON=.venv/bin/python tools/diff_across_threads.sh feed.zip 4  # merge order
```

The differentials need `java` and the pinned jar:

```bash
curl -sSL -o /tmp/gtfs-validator.jar \
  https://github.com/MobilityData/gtfs-validator/releases/download/v8.0.1/gtfs-validator-8.0.1-cli.jar
```

**What none of them covers is input nobody thought to build.** Every parity
defect found late was on a feed shape no probe carried, so a green run means
"matches on the feeds we have", not "matches".

**The differentials cannot see cost.** Every probe feed is a handful of rows, so
a rule that is quadratic in the number of calendar days emits identical notices
and a green diff. `measure_scale.py` exists for that. A full-table `list()` over
`stop_times.txt` is a bug on large feeds: real feeds reach 13 million rows.

## Conventions to apply when you touch the relevant code

Never as a bulk refactor.

- **A file over 300 lines** gets split by concern.
- **A `raise` site** routes through `src/gtfs_validator/error_ids.py`.
- **A value read from the environment** should not exist. This project is
  configured by CLI flags only, mirroring upstream's interface. `tools/` scripts
  are exempt, and read `GITHUB_TOKEN` only.
- **Anything affecting report output** means re-running the differentials before
  committing. Output shape is a contract.
- **Adding a notice code to `IMPLEMENTED`** needs a positive and a negative
  fixture in the same commit. Registration alone is not implementation.
- **Reading upstream Java to settle a question** means recording what you found
  in a comment. The next person should not have to clone it again.

## Repository layout

```
src/gtfs_validator/     the validator; rules/ is one module per notice code
tests/                  1,999 tests, no network, no jar required
tools/                  generators, oracles and differential harnesses
upstream/               the pin's recorded position and measurements
packaging/              the gtfs-lint rename alias, built separately
```

Probe feeds and the jar are deliberately not committed: they are large and
licensed separately. `tools/make_fixture_feed.py` builds the minimal one.
