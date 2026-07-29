"""Command line front end.

Flag names, defaults, argument contract and exit codes all mirror upstream's, so
that swapping implementations is a change of binary rather than a change of
invocation. The contract and the exit codes live in `cliargs`, with the
measurements that established them; the run itself lives in `pipeline`.

One flag is ours and upstream has no equivalent: `--fail-on-error`. It stays off
by default, because a feed carrying ERROR notices exits 0 on the jar and a
drop-in swap must not change exit status.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

from gtfs_validator import cliargs, fetch, htmlreport
from gtfs_validator.cliargs import EXIT_OK, EXIT_RUNNER, EXIT_USAGE, UsageError
from gtfs_validator.loading import _system_error
from gtfs_validator.notices import NoticeContainer
from gtfs_validator.pipeline import run_validation
from gtfs_validator.report import build_report, build_system_errors, dumps_json, write_text
from gtfs_validator.summary import FeedFacts, Register, RunConfig, build_summary
from gtfs_validator.version import VERSION

DATA = Path(__file__).resolve().parent / "data"
NOTICE_SCHEMA_JSON = "notice_schema.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gtfs-validator")
    parser.add_argument("-i", "--input", help="path to a GTFS zip or directory")
    parser.add_argument("-u", "--url", help="fully qualified URL of a GTFS zip to download")
    # No default. Upstream leaves this null and refuses the run unless one of
    # --output_base and --stdout is given, so defaulting it here would accept a
    # command line the jar rejects.
    parser.add_argument("-o", "--output_base", default=None)
    parser.add_argument("-c", "--country_code", default=None)
    # Upstream's DateForValidation is settable so a run is reproducible: a rule
    # reading "today" otherwise gives a different answer tomorrow. ISO_LOCAL_DATE,
    # matching upstream's Arguments, which is deliberately not the YYYYMMDD the
    # feeds themselves use. Measured: the jar rejects "20260601".
    parser.add_argument("-d", "--date", default=None, metavar="YYYY-MM-DD")
    parser.add_argument("-s", "--storage_directory", default=None)
    parser.add_argument("-e", "--system_errors_report_name", default="system_errors.json")
    parser.add_argument("-v", "--validation_report_name", default="report.json")
    parser.add_argument("-r", "--html_report_name", default="report.html")
    # Upstream's flag, same default of 1. At 1 the run is the sequential code
    # unchanged; higher values parallelise loading and rules with a deterministic
    # merge, so the report is identical at any thread count.
    parser.add_argument("-t", "--threads", type=int, default=1)
    parser.add_argument("-p", "--pretty", action="store_true", help="indent the JSON reports")
    parser.add_argument(
        "-n", "--export_notices_schema", action="store_true", help=f"write {NOTICE_SCHEMA_JSON}"
    )
    # Accepted and ignored: upstream uses it to skip a network check for a newer
    # release, and gtfs-validator never makes that call. Taking the flag anyway keeps
    # a wrapper script written for the jar working unchanged.
    parser.add_argument(
        "-svu", "--skip_validator_update", action="store_true", help="accepted, no effect"
    )
    parser.add_argument(
        "--stdout", action="store_true", help="write the validation report to stdout"
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help=(
            "exit 1 when any ERROR notice fires. Off by default because upstream "
            "exits 0 in that case and a drop-in swap must not change exit status"
        ),
    )
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    """The parsed arguments, exposed for tests and for the parallel dispatchers."""
    return _build_parser().parse_args(argv)


# ISO_LOCAL_DATE is fixed-width. Neither date.fromisoformat nor strptime is
# strict enough on its own: since 3.11 fromisoformat also accepts the compact
# "20260601" and ISO week dates, and strptime accepts "2026-6-1". Measured: the
# jar rejects all three with a DateTimeParseException, so accepting any of them
# would make our CLI take input the jar refuses.
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z", re.ASCII)


def _parse_date(value: str) -> date:
    if not _ISO_DATE_RE.match(value):
        raise ValueError(value)
    return datetime.strptime(value, "%Y-%m-%d").date()  # noqa: DTZ007


def _today() -> date:
    """LocalDate.now() in upstream's ValidationRunnerConfig, the system zone.

    Validating against a UTC date would expire a calendar a day early west of
    Greenwich, so this is deliberately local rather than aware.
    """
    return date.today()  # noqa: DTZ011


def _stamp() -> tuple[str, date]:
    """`validatedAt`, and the local date it falls on.

    `yyyy-MM-dd'T'HH:mm:ssXXX` from `ZonedDateTime.now()`, measured off the jar
    as `2026-07-29T09:29:06-04:00`: seconds resolution, offset with a colon,
    which is `%z` with a colon inserted.
    """
    now = datetime.now().astimezone()
    offset = now.strftime("%z")
    return (now.strftime("%Y-%m-%dT%H:%M:%S") + f"{offset[:3]}:{offset[3:]}", now.date())


def _export_notice_schema(output_base: str, pretty: bool) -> None:
    """Write the notice schema, generated from the jar's own exporter.

    Stored as the bytes the jar emits, so the default is a straight copy and `-p`
    re-serialises at Gson's two-space indent.
    """
    target = Path(output_base) / NOTICE_SCHEMA_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    text = (DATA / NOTICE_SCHEMA_JSON).read_text(encoding="utf-8")
    if pretty:
        text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    target.write_text(text, encoding="utf-8")


def _source(args, system_errors: NoticeContainer, work: str) -> str | None:
    """The local path to validate: `--input`, or whatever `--url` downloaded."""
    if args.url is None:
        return args.input
    target = fetch.target_for(args.storage_directory, Path(work))
    agent = fetch.user_agent(VERSION, ".".join(str(part) for part in sys.version_info[:3]))
    try:
        return str(fetch.download(args.url, target, agent))
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        _system_error(system_errors, args.url, exc)
        return None


def _config(args, validated_at: str, validation_date: date) -> RunConfig:
    """`--stdout` nulls the output directory and all three report names together."""
    return RunConfig(
        validator_version=VERSION,
        validated_at=validated_at,
        gtfs_input=Path(args.input).absolute().as_uri() if args.input else (args.url or ""),
        threads=max(1, args.threads),
        output_directory=None if args.stdout else args.output_base,
        system_errors_report_name=None if args.stdout else args.system_errors_report_name,
        validation_report_name=None if args.stdout else args.validation_report_name,
        html_report_name=None if args.stdout else args.html_report_name,
        country_code=cliargs.country_code(args.country_code),
        date_for_validation=validation_date,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        cliargs.check(args)
    except UsageError as exc:
        print(f"gtfs-validator: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.export_notices_schema:
        _export_notice_schema(args.output_base, args.pretty)
        if args.input is None and args.url is None:
            return EXIT_OK

    try:
        validation_date = _today() if args.date is None else _parse_date(args.date)
    except ValueError:
        print(f"gtfs-validator: --date must be ISO YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
        return EXIT_USAGE

    notices = NoticeContainer()
    system_errors = NoticeContainer()
    register = Register.new()
    validated_at, today = _stamp()
    started = time.monotonic()
    facts: FeedFacts | None = None
    opened = False

    with tempfile.TemporaryDirectory(prefix="gtfs-validator-fetch-") as work:
        source = _source(args, system_errors, work)
        if source is not None:
            facts, opened = run_validation(
                Path(source),
                notices,
                system_errors,
                cliargs.country_code(args.country_code) if args.country_code else "",
                validation_date,
                max(1, args.threads),
                register,
            )

    register.register("validate")
    config = _config(args, validated_at, validation_date)
    report = {
        "summary": build_summary(
            config, facts, time.monotonic() - started if opened else None, register
        ),
        **build_report(notices),
    }

    if args.stdout:
        print(dumps_json(report, pretty=args.pretty))
        return EXIT_OK if opened else EXIT_RUNNER

    out = Path(args.output_base)
    write_text(dumps_json(report, pretty=args.pretty), out / args.validation_report_name)
    htmlreport.write(
        out / args.html_report_name,
        notices=notices,
        facts=facts,
        config=config,
        validated_at=validated_at,
        different_date=today != validation_date,
    )
    write_text(
        dumps_json(build_system_errors(system_errors), pretty=args.pretty),
        out / args.system_errors_report_name,
    )

    # Upstream reserves a nonzero exit for a failure of the tool, not of the
    # feed: the v8.0.1 jar exits 0 on a feed carrying ERROR notices, and also on
    # one whose archive opened and whose tables then failed. Only an archive it
    # could not open at all is nonzero, and it is -1, which a shell reports as
    # 255. Both measured against the jar.
    if not opened:
        return EXIT_RUNNER
    if args.fail_on_error and notices.has_errors():
        return 1
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
