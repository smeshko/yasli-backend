"""`python -m yasli.ingest` — real R2-snapshot-to-Postgres ingest.

Default subcommand (no args, preserving the cron's invocation) runs the
weekly ingest pipeline: fetch from R2, validate, upsert, and run both
gated district-stamping passes in one transaction.

The ``restamp-districts`` subcommand runs the non-gated stamping passes
(addresses then institutions) inside their own transaction. No R2 fetch.
Used after a quarterly ГРАО refresh to propagate reassignments.
"""

from __future__ import annotations

import argparse
import json
import sys

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from yasli.config import Settings
from yasli.db import get_engine
from yasli.ingest import pipeline, r2
from yasli.ingest.district_stamp import (
    AddressesStampSummary,
    InstitutionsStampSummary,
    restamp_addresses_all,
    restamp_institutions_all,
)


def _validate_startup_config(*, require_r2: bool) -> None:
    """Raise ValueError if any required env var is missing/empty.

    The R2 vars are only checked when the chosen subcommand actually
    fetches from R2 — ``restamp-districts`` does not.
    """
    Settings()
    if require_r2:
        r2.validate_env()


def restamp_districts_in_session(
    session: Session,
) -> tuple[AddressesStampSummary, InstitutionsStampSummary]:
    """Run both non-gated restamp passes inside ``session``'s transaction.

    Exposed as a function so tests can drive it against an in-memory
    SQLite session without spinning up the CLI. The CLI handler below
    wraps this in a real Postgres session + transaction.
    """
    addresses_summary = restamp_addresses_all(session)
    institutions_summary = restamp_institutions_all(session)
    return addresses_summary, institutions_summary


def _emit_restamp_summary(
    addresses: AddressesStampSummary,
    institutions: InstitutionsStampSummary,
) -> None:
    print(
        "restamp-districts done "
        f"addresses={{primary:{addresses.primary_stamped},"
        f"fallback1:{addresses.fallback1_stamped},"
        f"fallback2:{addresses.fallback2_stamped}}} "
        f"addresses_district_unstamped={addresses.remaining_null} "
        f"institutions={{primary:{institutions.primary_stamped},"
        f"fallback:{institutions.fallback_stamped}}} "
        f"institutions_district_unstamped={institutions.remaining_null}",
        flush=True,
    )


def _run_ingest_subcommand() -> int:
    try:
        _validate_startup_config(require_r2=True)
    except (ValueError, r2.R2ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        summary = pipeline.run()
    except pipeline.UnsupportedSnapshotVersion as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except ValidationError as exc:
        print(f"error: snapshot failed validation: {exc}", file=sys.stderr)
        return 3
    except json.JSONDecodeError as exc:
        print(f"error: snapshot is not valid JSON: {exc}", file=sys.stderr)
        return 3
    except (BotoCoreError, ClientError) as exc:
        print(f"error: R2 fetch failed: {exc}", file=sys.stderr)
        return 4
    except SQLAlchemyError as exc:
        print(f"error: database error: {exc}", file=sys.stderr)
        return 5

    pipeline.emit_summary(summary)
    return 0


def _run_restamp_districts_subcommand() -> int:
    try:
        _validate_startup_config(require_r2=False)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        engine = get_engine()
        with Session(engine) as session, session.begin():
            addresses_summary, institutions_summary = restamp_districts_in_session(
                session
            )
    except SQLAlchemyError as exc:
        print(f"error: database error: {exc}", file=sys.stderr)
        return 5

    _emit_restamp_summary(addresses_summary, institutions_summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yasli.ingest",
        description=(
            "Pull snapshots/varna/latest.json from R2 and upsert into "
            "Postgres in one transaction (default), or run non-gated "
            "district-stamping passes (restamp-districts subcommand)."
        ),
    )
    subparsers = parser.add_subparsers(dest="cmd")
    subparsers.add_parser(
        "ingest", help="Full snapshot ingest (default behaviour with no args)."
    )
    subparsers.add_parser(
        "restamp-districts",
        help=(
            "Non-gated district-stamping for addresses + institutions. "
            "Invoked manually after a quarterly ГРАО reload."
        ),
    )
    args = parser.parse_args(argv)

    if args.cmd is None or args.cmd == "ingest":
        return _run_ingest_subcommand()
    if args.cmd == "restamp-districts":
        return _run_restamp_districts_subcommand()
    parser.error(f"unknown subcommand: {args.cmd}")
    return 2  # pragma: no cover - parser.error exits


if __name__ == "__main__":
    raise SystemExit(main())
