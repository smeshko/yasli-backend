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

from yasli.config import Settings
from yasli.seed import runner


def _emit_step(result: runner.StepResult) -> None:
    print(
        f"  {result.name:<22} {result.detail} ({result.elapsed_ms} ms)",
        flush=True,
    )


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
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yasli.seed",
        description=(
            "Bring a local Postgres to a production-like state from the "
            "committed data under data/ — migrations, ГРАО districts, the "
            "frozen snapshot, the legacy institutions and the institution "
            "locations. No R2 credential required."
        ),
    )
    subparsers = parser.add_subparsers(dest="cmd")
    subparsers.add_parser(
        "seed", help="Run the full seed (the default with no arguments)."
    )
    args = parser.parse_args(argv)

    if args.cmd is None or args.cmd == "seed":
        return _run_seed_subcommand()
    parser.error(f"unknown subcommand: {args.cmd}")
    return runner.EXIT_CONFIG  # pragma: no cover - parser.error exits


if __name__ == "__main__":
    raise SystemExit(main())
