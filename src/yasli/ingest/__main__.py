"""`python -m yasli.ingest` — schema-presence stub.

Validates configuration, opens a session against the configured database
and logs the current `institutions` row count, then exits 0. Real ingest
behaviour (snapshot fetch + upsert) lands in s06; this stub exists so the
cron service fails loud on a missing DB or unmigrated schema.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from yasli.config import Settings
from yasli.db import get_db, get_engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yasli.ingest",
        description="Ingest snapshots from R2 into Postgres (stub).",
    )
    parser.parse_args(argv)

    try:
        Settings()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print("yasli.ingest: stub run; no-op until s06")

    get_engine()
    session = next(get_db())
    try:
        count = session.execute(text("SELECT count(*) FROM institutions")).scalar_one()
    finally:
        session.close()
    print(f"yasli.ingest: institutions row count = {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
