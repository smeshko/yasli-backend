"""`python -m yasli.ingest` — no-op stub.

Validates configuration via `Settings()` (so the cron service fails fast
when `DATABASE_URL` is missing), prints a single line, and exits 0. Real
ingest behaviour is added by a later change (`backend-ingest`).
"""

from __future__ import annotations

import argparse
import sys

from yasli.config import Settings


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
