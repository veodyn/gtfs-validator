# gtfs-validator (Python)

A drop-in replacement for the canonical GTFS validator, written in pure Python.
It needs no JVM and has no runtime dependencies.

This project shares a name with the software it reimplements. Below, "upstream"
always means [MobilityData's Java gtfs-validator][upstream], which this is an
independent reimplementation of and is not affiliated with.

```bash
pip install gtfs-validator
gtfs-validator -i feed.zip -o out/
```

You get the same three files the Java validator writes, with the same contents:
`report.json`, `system_errors.json` and `report.html`.

> Status: pre-release. The rule set is complete and the CLI matches the jar, both
> held in place by differential tests against the real thing. Test coverage of
> the CLI and the report summary is still thin, and no real-world feed has been
> through the HTML report path yet.

## Why this exists

Upstream is Java. If your pipeline is Python, you either ship a JVM in every
container and CI runner to run it, or you fall back on `transitfeed`, which last
saw a release in 2018.

This is the same rule set, reimplemented, so that validating a feed costs a
`pip install` instead of a base image.

## How close is it?

Close enough that swapping the binary is meant to be the entire change. That
claim is tested rather than asserted: both reports run against the pinned jar on
the same feeds, and any difference fails the build.

| | |
|---|---|
| Notice codes | 173 of upstream's 176. The other three are deprecated classes upstream never constructs. |
| `report.json` | Identical, including the `summary` block and the order of keys inside it. |
| `report.html` | Byte-identical. |
| CLI flags | All 13, plus `--fail-on-error`, which upstream has no equivalent for. |
| Exit codes | Identical, including the surprising ones. |

Two fields differ on purpose. `summary.validatorVersion` reports this project's
own version rather than `8.0.1`, because the field names the validator that ran
and an archived report should say which of the two produced it. And
`summary.memoryUsageRecords` carries Python measurements under Java's field
names, because the JVM heap concepts they are named for have no CPython
equivalent. The full list is below.

### Exit codes are worth reading twice

They are upstream's, and they are not what most people guess:

| Situation | Exit |
|---|---|
| Feed is fine | 0 |
| Feed carries ERROR notices | 0 |
| Archive opened, then a table failed to parse | 0, with the failure in `system_errors.json` |
| Archive could not be opened at all | 255 |
| Bad combination of flags | 1 |

A feed full of errors exits 0 because the report is the output, and a nonzero
status means the tool itself failed. If you want the other behaviour, pass
`--fail-on-error`. It is off by default so that swapping the binary cannot
silently change what your pipeline does.

## Deliberate differences

Everything here was measured against the pinned jar and kept on purpose. Anything
*not* on this list is a bug worth reporting.

**Floating point, in the last digit only.** Distances and coordinates that pass
through S2 geometry can differ in their final digit, because one ulp of `sin`
inside S2's `toPoint` gets amplified by cancellation. Notice codes and counts are
identical; only a context value's last digit moves. Worst case measured for a
latitude is 2.8e-14 degrees, and it affects 52.9% of transfer-sized pairs for the
`S2Point` overload. This is the one difference you are likely to see on a real
feed.

**Number formatting, on a handful of values.** JDK 17 predates the shortest-repr
algorithm, so it sometimes prints more digits than the shortest decimal that
round-trips, where Python prints the shortest. Upstream is not wrong here, it is
old, and this shrinks to nothing when the pin moves past JDK 19.

**Two message strings.** `malformed_json` and `csv_parsing_failed` carry Java
exception text on upstream's side that a Python implementation cannot reproduce
verbatim. The codes, counts and every other context field match.

**Four things in the report and CLI.** `summary.validatorVersion` names this
project rather than `8.0.1`. `summary.memoryUsageRecords` carries Python
measurements under Java's field names, since the JVM heap concepts they are named
for have no CPython equivalent. `feedInfo["Feed Language"]` is always English,
where upstream's answer depends on the host JVM's locale, because a report should
not change with the machine that produced it. And `--url` without
`--storage_directory` streams the download to a temporary file rather than into
memory, which keeps a several-hundred-megabyte feed off the heap.

**One known defect, not a difference.** A `shape_dist_traveled` of `NaN` draws
`number_out_of_range` here and nothing from upstream, because Java's
`Double.compareTo` orders NaN above positive infinity so neither bound can fire.
That one is ours to fix.

## What it will not do

GTFS-Realtime is out of scope here, as it is upstream. Analysis is out of scope
too: this checks feeds against a rule set, and for working with the feed data
itself, [`gtfs-kit`][gtfs-kit] is good and does not overlap.

It also will not second-guess upstream. Where the Java validator's behaviour
looks wrong, this reproduces it and records the disagreement in writing, because
matching a rule set someone else owns is the job.

## Working on it

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Six checks cover different ground, and each has caught defects the others could
not:

```bash
python -m pytest                                    # behaviour, per unit
ruff check src/ tests/ tools/                       # style and the lint rules
DATE=2026-06-01 PYTHON=.venv/bin/python \
  tools/diff_against_upstream.sh feed.zip jar.jar   # notices, per feed
DATE=2026-06-01 PYTHON=.venv/bin/python \
  tools/diff_full_output_against_upstream.sh feed.zip jar.jar   # summary + HTML
PYTHONPATH=src python tools/measure_scale.py        # time and memory, one big feed
python tools/diff_hashmap_against_jdk.py            # HashMap order, 316 orders
python tools/diff_farmhash_against_guava.py         # Guava's fingerprint, 238 cases
```

The differential compares codes, counts and every sample's context. What it
cannot see is cost. Probe feeds are a handful of rows, so a rule that is
quadratic in calendar length emits identical notices and a green diff.
`measure_scale.py` exists for that.

The last two compare a ported Java semantic against the JDK and against Guava,
rather than comparing validators. That sounds excessive until you learn that
`HashMap` iteration order decides which 1,000 notices a report keeps, and that
the harness found a `farmHashFingerprint64` transcribed with one of its loads
eight bytes late, wrong only for inputs between 33 and 64 bytes.

What none of them covers is input nobody thought to build. Every parity defect
found late was on a feed shape no probe carried, so a green run means "matches on
the feeds we have".

## Relationship to upstream

An independent reimplementation, not an official port, not affiliated with
MobilityData and not endorsed by them. Notice codes, severities and context field
names come from their Apache-2.0 project. The shared name describes what the
software does; it is not a claim of origin.

The pin is v8.0.1. `tools/check_upstream.py` reports when the validator or the
GTFS spec moves past it, and those are two different signals. Parity is with the
jar, so a spec change MobilityData have merged but not shipped is recorded in
`upstream/pending-spec-changes.md` and changes nothing here until a release
implements it.

## License

MIT; see [`LICENSE`](LICENSE).

A few files are copied from upstream rather than derived from it, and stay under
its Apache-2.0 licence: the HTML report template, and two data files generated by
running the jar. [`NOTICE`](NOTICE) names each one and explains the shared name.

[upstream]: https://github.com/MobilityData/gtfs-validator
[gtfs-kit]: https://pypi.org/project/gtfs-kit/
