"""The `summary` object of `report.json`, which upstream writes and we did not.

`report.json` is `{"summary": {...}, "notices": [...]}` on the jar's side. Ours
carried only the second key until 2026-07-29, and the differential never noticed
because it extracts `report["notices"]` and compares nothing else. A comparison
is only as wide as what it reads.

Field order below is `JsonReportSummary`'s declaration order, which is what Gson
serialises, and **null-valued fields are omitted entirely**: a key that was never
set disappears from the file while a key set to `""` stays. Those are different
states and the report shows the difference, so `_drop_nulls` is not a tidy-up.

The work is in two halves because the store is only open for one of them.
`feed_facts` runs while the tables are still readable; `build_summary` runs
afterwards and needs nothing but its result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from gtfs_validator.rules.feedview import FeedView
from gtfs_validator.summary import features, metadata
from gtfs_validator.summary.memory import Register

__all__ = [
    "IMPLEMENTATION_DEPENDENT",
    "RUN_DEPENDENT",
    "FeedFacts",
    "Register",
    "RunConfig",
    "build_summary",
    "feed_facts",
    "normalise",
]

# Summary fields that legitimately differ between two runs of gtfs-validator itself:
# a wall clock, an elapsed time, a memory reading, and wherever the output went.
# Adding the summary made `report.json` non-reproducible for the first time, so
# every byte comparison in the tree has to know this set. It is here rather than
# in each harness so there is one definition to keep honest.
RUN_DEPENDENT = ("validatedAt", "validationTimeSeconds", "memoryUsageRecords", "outputDirectory")

# Also differ from the jar, deliberately and permanently. `validatorVersion`
# names the validator that ran, and gtfs-validator does not claim to be 8.0.1;
# `gtfsInput` is an absolute path, so it differs whenever the two sides are not
# handed the identical string. A sixth entry in either tuple is a spec change,
# not a convenience: see 2026-07-29-cli-parity-design.md.
IMPLEMENTATION_DEPENDENT = ("validatorVersion", "gtfsInput")


def normalise(report: dict, *, against_jar: bool = False) -> dict:
    """A report with the fields that cannot be compared byte for byte removed.

    Never widen this to make a comparison pass. A red diff is the deliverable.
    """
    drop = set(RUN_DEPENDENT) | (set(IMPLEMENTATION_DEPENDENT) if against_jar else set())
    summary = {k: v for k, v in (report.get("summary") or {}).items() if k not in drop}
    return {**report, "summary": summary}


@dataclass(frozen=True)
class RunConfig:
    """What the summary needs from the invocation rather than from the feed.

    `ValidationRunnerConfig` upstream. The output directory and all three report
    names are None under `--stdout`, which upstream signals by writing null for
    every one of them, so they vanish from the file together.
    """

    validator_version: str
    validated_at: str
    gtfs_input: str
    threads: int
    output_directory: str | None
    system_errors_report_name: str | None
    validation_report_name: str | None
    html_report_name: str | None
    country_code: str
    date_for_validation: date


@dataclass(frozen=True)
class FeedFacts:
    """Everything the summary reads out of the feed, gathered before the store closes.

    Also what the HTML report renders, which is why `service_window` is kept: the
    JSON carries only the start and end, and the page shows the joined string.
    """

    feed_info: dict[str, str]
    feed_info_display: dict[str, str]
    agencies: list[dict[str, str]]
    files: list[str]
    counts: dict[str, int]
    gtfs_features: list[str] = field(default_factory=list)
    feature_urls: dict[str, str] = field(default_factory=dict)


def feed_facts(view: FeedView, present: frozenset[str]) -> FeedFacts:
    """Read the feed half while the tables are still open."""
    found = features.present(view)
    return FeedFacts(
        feed_info=metadata.feed_info(view),
        feed_info_display=metadata.feed_info_display(view),
        agencies=metadata.agencies(view),
        files=metadata.filenames(present),
        counts=metadata.counts(view),
        gtfs_features=[feature.name for feature in found],
        feature_urls={feature.name: feature.doc_url for feature in found},
    )


def _drop_nulls(payload: dict[str, object]) -> dict[str, object]:
    """Gson's default: a null field is absent from the JSON, not present as null."""
    return {key: value for key, value in payload.items() if value is not None}


def build_summary(
    config: RunConfig,
    facts: FeedFacts | None,
    validation_time_seconds: float | None,
    register: Register | None = None,
) -> dict[str, object]:
    """The summary object, ready to serialise.

    `facts` is None when the feed never opened, which upstream logs as "No feed
    metadata" while still writing the report. The feed-derived keys are then
    absent and the invocation half still lands, so a report always has a summary.
    """
    payload: dict[str, object] = {
        "validatorVersion": config.validator_version,
        "validatedAt": config.validated_at,
        "gtfsInput": config.gtfs_input,
        "threads": config.threads,
        "outputDirectory": config.output_directory,
        "systemErrorsReportName": config.system_errors_report_name,
        "validationReportName": config.validation_report_name,
        "htmlReportName": config.html_report_name,
        "countryCode": config.country_code,
        "dateForValidation": config.date_for_validation.isoformat(),
    }
    if facts is not None:
        payload["feedInfo"] = facts.feed_info
        payload["agencies"] = facts.agencies
        payload["files"] = facts.files
        payload["validationTimeSeconds"] = validation_time_seconds
        payload["memoryUsageRecords"] = register.as_list() if register else None
        payload["counts"] = facts.counts
        payload["gtfsFeatures"] = facts.gtfs_features
    return _drop_nulls(payload)
