"""`python -m yasli.seed` — the CLI.

With no arguments it runs the full seed, printing one line per step as
that step finishes, then a closing line carrying the frozen snapshot's
``scraped_at``. A failed step names itself on stderr and stops the run;
later steps do not execute.

Exit codes follow the `yasli.ingest` convention: 0 success, 2 config,
3 data, 4 fetch/precondition, 5 database.
"""

from __future__ import annotations

import argparse
import sys

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yasli.config import Settings
from yasli.db import get_engine
from yasli.ingest import r2
from yasli.seed import freeze, runner, verify


def _emit_step(result: runner.StepResult) -> None:
    print(
        f"  {result.name:<22} {result.detail} ({result.elapsed_ms} ms)",
        flush=True,
    )


def _run_verify_subcommand() -> int:
    """Re-check a seeded database and name everything that is wrong with it."""
    try:
        Settings()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return runner.EXIT_CONFIG

    print("verifying the local database against the committed artifacts", flush=True)
    try:
        with Session(get_engine()) as session:
            result = verify.run_checks(session)
    except SQLAlchemyError as exc:
        print(f"error: database error: {exc}", file=sys.stderr)
        return runner.EXIT_DATABASE

    print(verify.format_result(result), flush=True)
    return 0 if result.ok else runner.EXIT_PRECONDITION


def _run_freeze_subcommand(args: argparse.Namespace) -> int:
    """Regenerate the committed snapshot. Needs R2 credentials; see freeze.py."""
    try:
        Settings()
        # Same message `python -m yasli.ingest` already produces.
        r2.validate_env()
    except (ValueError, r2.R2ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return runner.EXIT_CONFIG

    print("freezing the committed snapshot", flush=True)
    try:
        report = freeze.run_freeze(dry_run=args.dry_run)
    except freeze.FreezeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return runner.EXIT_DATA
    except (BotoCoreError, ClientError) as exc:
        print(f"error: R2 fetch failed: {exc}", file=sys.stderr)
        return runner.EXIT_PRECONDITION

    print(report.format(), flush=True)
    return 0


def _run_seed_subcommand() -> int:
    try:
        Settings()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return runner.EXIT_CONFIG

    print("seeding a production-like local database", flush=True)
    try:
        summary = runner.run_seed(on_step=_emit_step)
    except runner.SeedStepFailed as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            f"seed failed at step {exc.step!r}; the database is half-seeded. "
            "Fix the cause and re-run, or `just db-reset && just be-seed` for "
            "a clean start.",
            file=sys.stderr,
        )
        return exc.exit_code

    scraped = summary.scraped_at.isoformat() if summary.scraped_at else "unknown"
    print(
        f"seed done steps={len(summary.steps)} snapshot={scraped} "
        f"elapsed_ms={summary.elapsed_ms}",
        flush=True,
    )

    # Verification is the seed's last act, not an optional follow-up: a
    # command that reports success over a half-seeded database is the
    # failure mode YAS-21 complains about.
    return _run_verify_subcommand()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yasli.seed",
        description=(
            "Bring a local Postgres to a production-like state from the "
            "committed data under data/ — migrations, ГРАО districts, the "
            "frozen snapshot and the institution locations. "
            "No R2 credential required."
        ),
    )
    subparsers = parser.add_subparsers(dest="cmd")
    subparsers.add_parser(
        "seed", help="Run the full seed (the default with no arguments)."
    )
    freeze_parser = subparsers.add_parser(
        "freeze",
        help=(
            "Maintainer-only: regenerate data/seed/snapshot.json.gz from R2. "
            "Needs the R2_* variables."
        ),
    )
    freeze_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change and write nothing.",
    )
    subparsers.add_parser(
        "verify",
        help=(
            "Re-check a seeded database against the committed artifacts and "
            "exit non-zero naming what is missing. Runs automatically at the "
            "end of a seed."
        ),
    )
    args = parser.parse_args(argv)

    if args.cmd is None or args.cmd == "seed":
        return _run_seed_subcommand()
    if args.cmd == "verify":
        return _run_verify_subcommand()
    if args.cmd == "freeze":
        return _run_freeze_subcommand(args)
    parser.error(f"unknown subcommand: {args.cmd}")
    return runner.EXIT_CONFIG  # pragma: no cover - parser.error exits


if __name__ == "__main__":
    raise SystemExit(main())
