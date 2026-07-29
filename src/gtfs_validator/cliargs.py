"""Upstream's `Arguments.validate()`, and the exit codes `Main` pairs with it.

Split from `cli` because the contract is a closed set of rules worth reading on
its own, and because a wrapper script sees only the exit status: getting these
numbers wrong is indistinguishable, from the outside, from getting the validation
wrong.

Measured against the pinned jar rather than read off the source alone:

| Situation | Jar | Us, before | Us, now |
|---|---|---|---|
| `--help` | 0 | 0 | 0 |
| illegal flag combination | 1 | 2 | 1 |
| feed cannot be opened at all | 255 | 1 | 255 |
| feed opens, a table raises | 0 | 1 | 0 |
| clean run | 0 | 0 | 0 |

The last two rows are the ones that mattered and neither was guessed.
`ValidationRunner.run` returns `Status.SYSTEM_ERRORS` only inside the branch
where `gtfsInput == null`, so a table that fails *after* the archive opened still
exits 0 with the failure recorded in `system_errors.json`. We exited 1 for both,
on the reasoning that an incomplete report is a tool failure. That reasoning is
defensible and it is not upstream's, and a drop-in swap does not get to hold its
own opinion about exit status.
"""

from __future__ import annotations

# `Main` exits -1 on a runner failure, which a shell reports as 255.
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_RUNNER = 255


class UsageError(Exception):
    """An illegal combination of flags. The message is upstream's, verbatim."""


def check(args) -> None:
    """Raise `UsageError` for any combination upstream refuses.

    Order matters: upstream returns on the first failure, so a call passing both
    `--input` and `--url` with no `--output_base` reports the input clash rather
    than the missing output. A wrapper script parsing stderr sees that ordering.
    """
    exporting_only = args.export_notices_schema and args.input is None and args.url is None
    if exporting_only:
        if args.output_base is None:
            raise UsageError(
                "Must provide --output_base when using --export_notices_schema "
                "without --input or --url"
            )
        return

    if args.input is None and args.url is None:
        raise UsageError(
            "One of the two following CLI parameter must be provided: '--input' and '--url'"
        )
    if args.input is not None and args.url is not None:
        raise UsageError(
            "The two following CLI parameters cannot be provided at the same time:"
            " '--input' and '--url'"
        )
    if args.storage_directory is not None and args.url is None:
        raise UsageError(
            "CLI parameter '--storage_directory' must not be provided if '--url' is not provided"
        )
    if args.stdout and args.output_base is not None:
        raise UsageError("Cannot use --stdout with --output_base. Use one or the other.")
    if args.output_base is None and not args.stdout:
        raise UsageError("Must provide either --output_base or --stdout")


def country_code(value: str | None) -> str:
    """`CountryCode.forStringOrUnknown(...).getCountryCode()`.

    `ZZ` is the unknown country, and it is what the summary reports when `-c` was
    not given. Measured on the jar: a run with no `-c` writes `"countryCode":
    "ZZ"`, not an empty string.
    """
    if not value:
        return "ZZ"
    return value.upper()
